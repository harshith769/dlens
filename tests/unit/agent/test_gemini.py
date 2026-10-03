import base64
from types import SimpleNamespace as NS

import pytest
from google.genai import errors
from google.genai import types as gt

from dlens.agent.llm import make_client
from dlens.agent.llm.cache import ResponseCache, cache_key
from dlens.agent.llm.gemini import GeminiConfigError, GeminiProvider
from dlens.agent.llm.types import Message, ProviderError, ToolCall, ToolSpec

from .conftest import user

SIG = b"\x00\x01opaque-signature\xff"
SIG_B64 = base64.b64encode(SIG).decode()


class FakeModels:
    def __init__(self, response=None, err=None):
        self.response, self.err, self.kwargs = response, err, None

    def generate_content(self, **kwargs):
        self.kwargs = kwargs
        if self.err:
            raise self.err
        return self.response


def fake_client(response=None, err=None):
    return NS(models=FakeModels(response, err))


def response(parts, prompt=10, out=4):
    return NS(
        candidates=[NS(content=NS(parts=parts))],
        usage_metadata=NS(prompt_token_count=prompt, candidates_token_count=out),
    )


def fc_part(name="trace_upstream", args=None, sig=SIG):
    return gt.Part(
        function_call=gt.FunctionCall(name=name, args=args or {"column_id": "a.b"}),
        thought_signature=sig,
    )


def provider(client, **kw):
    return GeminiProvider("gemini-3.5-flash-lite", client=client, **kw)


def test_config_disables_afc_and_uses_defaults():
    c = fake_client(response([gt.Part(text="hi")]))
    resp = provider(c).send(user("q"), [ToolSpec(name="t", description="d")])
    cfg = c.models.kwargs["config"]
    assert c.models.kwargs["model"] == "gemini-3.5-flash-lite"
    assert cfg.automatic_function_calling.disable is True
    assert cfg.temperature == 1.0
    assert cfg.thinking_config is None
    assert cfg.tools[0].function_declarations[0].name == "t"
    assert (resp.text, resp.usage.input_tokens, resp.usage.output_tokens) == ("hi", 10, 4)


def test_temperature_and_thinking_configurable_and_in_cache_params():
    c = fake_client(response([gt.Part(text="hi")]))
    p = provider(c, temperature=0.4, thinking_level="low")
    p.send(user("q"), None)
    cfg = c.models.kwargs["config"]
    assert cfg.temperature == 0.4
    assert cfg.thinking_config.thinking_level == gt.ThinkingLevel.LOW
    base = provider(c).params
    assert p.params != base
    k = lambda pr: cache_key("gemini", pr.model, user("q"), None, pr.params)  # noqa: E731
    assert k(p) != k(provider(c)) != k(provider(c, temperature=0.4))


def test_from_env(monkeypatch):
    monkeypatch.setattr("google.genai.Client", lambda **kw: fake_client())
    env = {
        "DLENS_GEMINI_MODEL": "gemini-3.5-flash-lite",
        "GEMINI_API_KEY": "secret",
        "DLENS_GEMINI_TEMPERATURE": "0.7",
        "DLENS_GEMINI_THINKING": "minimal",
    }
    p = GeminiProvider.from_env(env)
    assert (p.model, p.temperature, p.thinking_level) == ("gemini-3.5-flash-lite", 0.7, "MINIMAL")


@pytest.mark.parametrize("model", ["", "gemini-flash-lite-latest"])
def test_rejects_empty_and_latest_model(model):
    with pytest.raises(GeminiConfigError):
        GeminiProvider(model, client=fake_client())


def test_missing_key_error_does_not_leak(monkeypatch):
    monkeypatch.setattr("google.genai.Client", lambda **kw: pytest.fail("SDK client constructed"))
    with pytest.raises(GeminiConfigError, match="GEMINI_API_KEY is not set"):
        GeminiProvider.from_env({"DLENS_GEMINI_MODEL": "gemini-3.5-flash-lite"})


def test_bad_thinking_level_rejected():
    with pytest.raises(GeminiConfigError):
        provider(fake_client(), thinking_level="extreme")


def test_make_client_gemini_makes_no_network_call(tmp_path, monkeypatch):
    monkeypatch.setattr("google.genai.Client", lambda **kw: fake_client())
    env = {
        "DLENS_GEMINI_MODEL": "gemini-3.5-flash-lite",
        "GEMINI_API_KEY": "k",
        "DLENS_CACHE_DIR": str(tmp_path / "c"),
        "DLENS_STATE_DIR": str(tmp_path / "s"),
    }
    client = make_client("gemini", env)
    assert client.provider.name == "gemini"
    assert client.quota.budgets["gemini"] == 400


def test_signature_preserved_response_to_message_to_request():
    c = fake_client(response([gt.Part(text="thinking", thought=True), fc_part()]))
    p = provider(c)
    resp = p.send(user("q"), None)
    assert resp.text == ""  # thought parts are not narrated
    assert resp.tool_calls[0].provider_meta == {"thought_signature": SIG_B64}
    history = [
        *user("q"),
        resp.as_message(),
        Message(role="tool", content="{}", name="trace_upstream", tool_call_id="call_0"),
    ]
    c.models.response = response([gt.Part(text="final")])
    p.send(history, None)
    sent = c.models.kwargs["contents"]
    assert sent[1].role == "model"
    assert sent[1].parts[0].thought_signature == SIG
    assert sent[1].parts[0].function_call.name == "trace_upstream"
    assert sent[2].parts[0].function_response.name == "trace_upstream"


def test_signature_survives_cache_roundtrip(tmp_path):
    c = fake_client(response([fc_part()]))
    p = provider(c)
    resp = p.send(user("q"), None)
    cache = ResponseCache(tmp_path / "c.sqlite")
    cache.put("k", resp)
    again = ResponseCache(tmp_path / "c.sqlite").get("k")
    assert again is not None
    history = [
        *user("q"),
        again.as_message(),
        Message(role="tool", content="x", name="trace_upstream"),
    ]
    c.models.response = response([gt.Part(text="ok")])
    p.send(history, None)
    assert c.models.kwargs["contents"][1].parts[0].thought_signature == SIG


def test_call_without_signature_has_empty_meta():
    c = fake_client(response([fc_part(sig=None)]))
    assert provider(c).send(user("q"), None).tool_calls[0].provider_meta == {}


def test_parallel_tool_results_share_one_turn_and_system_goes_to_instruction():
    c = fake_client(response([gt.Part(text="ok")]))
    calls = [ToolCall(id="call_0", name="a"), ToolCall(id="call_1", name="b")]
    history = [
        Message(role="system", content="be brief"),
        Message(role="user", content="q"),
        Message(role="assistant", tool_calls=calls),
        Message(role="tool", content="1", name="a"),
        Message(role="tool", content="2", name="b"),
    ]
    provider(c).send(history, None)
    kw = c.models.kwargs
    assert kw["config"].system_instruction == "be brief"
    assert [x.role for x in kw["contents"]] == ["user", "model", "user"]
    assert len(kw["contents"][2].parts) == 2


def test_api_error_maps_with_status_and_retryable():
    err = errors.APIError(429, {"error": {"message": "rate", "status": "RESOURCE_EXHAUSTED"}})
    with pytest.raises(ProviderError) as ei:
        provider(fake_client(err=err)).send(user("q"), None)
    assert (ei.value.status_code, ei.value.retryable) == (429, True)
    err = errors.APIError(400, {"error": {"message": "bad", "status": "INVALID_ARGUMENT"}})
    with pytest.raises(ProviderError) as ei:
        provider(fake_client(err=err)).send(user("q"), None)
    assert ei.value.retryable is False
