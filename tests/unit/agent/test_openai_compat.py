"""OpenAI-compatible adapter (ADR 0012, S11 step 2), on a fake httpx transport: no network."""

import json
from pathlib import Path
from typing import Any

import httpx
import pytest

from dlens.agent.llm import ProviderError, make_client
from dlens.agent.llm.base import LLMClient
from dlens.agent.llm.cache import ResponseCache
from dlens.agent.llm.openai_compat import (
    GROQ_BASE_URL,
    OpenAICompatConfigError,
    OpenAICompatProvider,
    is_local,
)
from dlens.agent.llm.quota import QuotaCounter
from dlens.agent.llm.ratelimit import RateLimiter
from dlens.agent.llm.types import Message, ToolSpec
from dlens.agent.runlog import RunLogger, RunRecord, Step

from .conftest import user

LOCAL = "http://localhost:11434/v1"
REMOTE = "https://llm.example.com/v1"
SENTINEL = "sk-SENTINEL-do-not-leak-0123456789"
SCHEMA = {"type": "object", "properties": {"answer_text": {"type": "string"}}}


class Fake:
    """Records every request; answers with ``reply`` (a dict -> 200 JSON) or ``(status, text)``."""

    def __init__(self, reply: Any = None, exc: Exception | None = None) -> None:
        self.reply = reply if reply is not None else completion("ok")
        self.exc = exc
        self.requests: list[httpx.Request] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        if self.exc is not None:
            raise self.exc
        if isinstance(self.reply, tuple):
            return httpx.Response(self.reply[0], text=self.reply[1])
        return httpx.Response(200, json=self.reply)

    @property
    def body(self) -> dict[str, Any]:
        return json.loads(self.requests[-1].content)


def completion(content: str | None = "", calls: list[dict[str, Any]] | None = None) -> dict:
    msg: dict[str, Any] = {"role": "assistant", "content": content}
    if calls:
        msg["tool_calls"] = calls
    return {"choices": [{"message": msg}], "usage": {"prompt_tokens": 11, "completion_tokens": 7}}


def provider(fake: Fake, base_url: str = LOCAL, **kw: Any) -> OpenAICompatProvider:
    env = kw.pop("env", {})
    return OpenAICompatProvider(
        kw.pop("name", "openai"),
        base_url,
        kw.pop("model", "qwen3:4b-instruct-2507-q4_K_M"),
        kw.pop("key_env", None),
        env=env,
        client=httpx.Client(transport=httpx.MockTransport(fake)),
        **kw,
    )


def client_for(prov: OpenAICompatProvider, tmp_path: Path, budget: int | None = 10) -> LLMClient:
    return LLMClient(
        prov,
        ResponseCache(tmp_path / "cache" / "llm.sqlite"),
        QuotaCounter(tmp_path / "state" / "quota.sqlite", {prov.name: budget}),
        RateLimiter(None),
    )


# -- request shape ---------------------------------------------------------------------------


def test_text_call_shape_and_usage() -> None:
    fake = Fake(completion("hello"))
    resp = provider(fake).send(user("hi"), None)
    req = fake.requests[0]
    assert str(req.url) == f"{LOCAL}/chat/completions"
    assert fake.body == {
        "model": "qwen3:4b-instruct-2507-q4_K_M",
        "messages": [{"role": "user", "content": "hi"}],
        "temperature": 0.0,
    }
    assert "authorization" not in req.headers  # no key configured, none sent
    assert (resp.text, resp.usage.input_tokens, resp.usage.output_tokens) == ("hello", 11, 7)


def test_think_block_is_stripped() -> None:
    assert provider(Fake(completion("<think>x</think>answer"))).send(user("q"), None).text == (
        "answer"
    )


@pytest.mark.parametrize(
    ("mode", "want"),
    [
        (
            "json_schema",
            {"type": "json_schema", "json_schema": {"name": "answer", "schema": SCHEMA}},
        ),
        ("json_object", {"type": "json_object"}),
        ("off", None),
    ],
)
def test_response_schema_by_json_mode(mode: str, want: Any) -> None:
    fake = Fake(completion('{"answer_text": "x"}'))
    resp = provider(fake, json_mode=mode).send(user("q"), None, SCHEMA)
    assert fake.body.get("response_format") == want
    assert resp.text == '{"answer_text": "x"}'


def test_tool_call_round_trip() -> None:
    calls = [
        {"id": "srv_rand_1", "type": "function",
         "function": {"name": "trace_upstream", "arguments": '{"column_id": "a.b"}'}},
        {"id": "srv_rand_2", "type": "function",
         "function": {"name": "impact_downstream", "arguments": '{"column_id": "c.d"}'}},
    ]  # fmt: skip
    fake = Fake(completion(None, calls))
    spec = ToolSpec(name="trace_upstream", description="d", parameters={"type": "object"})
    resp = provider(fake).send(user("q"), [spec])
    fn = {"name": "trace_upstream", "description": "d", "parameters": {"type": "object"}}
    assert fake.body["tools"] == [{"type": "function", "function": fn}]
    assert [(c.id, c.name, c.arguments) for c in resp.tool_calls] == [
        ("call_0", "trace_upstream", {"column_id": "a.b"}),
        ("call_1", "impact_downstream", {"column_id": "c.d"}),
    ]
    assert resp.text == ""
    # the history replays as OpenAI messages: assistant tool_calls, then tool results by id
    history = [
        *user("q"),
        resp.as_message(),
        Message(role="tool", content='{"paths": []}', tool_call_id="call_0", name="trace_upstream"),
    ]
    provider(fake).send(history, [spec])
    sent = fake.body["messages"]
    assert sent[1] == {
        "role": "assistant",
        "content": None,
        "tool_calls": [
            {"id": "call_0", "type": "function",
             "function": {"name": "trace_upstream", "arguments": '{"column_id": "a.b"}'}},
            {"id": "call_1", "type": "function",
             "function": {"name": "impact_downstream", "arguments": '{"column_id": "c.d"}'}},
        ],
    }  # fmt: skip
    assert sent[2] == {"role": "tool", "tool_call_id": "call_0", "content": '{"paths": []}'}


def test_malformed_tool_arguments_are_a_tool_call_error() -> None:
    bad = [{"id": "x", "type": "function", "function": {"name": "t", "arguments": "{not json"}}]
    with pytest.raises(ProviderError, match="tool call"):  # the loop's repair hook matches this
        provider(Fake(completion(None, bad))).send(user("q"), None)


# -- errors ----------------------------------------------------------------------------------


@pytest.mark.parametrize(("status", "retryable"), [(429, True), (503, True), (400, False)])
def test_http_errors_map_to_provider_error(status: int, retryable: bool) -> None:
    with pytest.raises(ProviderError) as e:
        provider(Fake((status, "rate limited " * 100))).send(user("q"), None)
    assert (e.value.status_code, e.value.retryable) == (status, retryable)
    assert len(str(e.value)) < 400  # body clipped
    assert e.value.__cause__ is None and e.value.__suppress_context__


def test_transport_error_is_retryable_and_unchained() -> None:
    with pytest.raises(ProviderError) as e:
        provider(Fake(exc=httpx.ConnectError("refused"))).send(user("q"), None)
    assert e.value.retryable and e.value.__cause__ is None


def test_unreadable_response() -> None:
    with pytest.raises(ProviderError, match="unreadable"):
        provider(Fake({"nope": 1})).send(user("q"), None)


# -- configuration ---------------------------------------------------------------------------


def test_cache_key_changes_with_base_url_and_model(tmp_path: Path) -> None:
    keys = set()
    env = {"K": "secret"}
    for url, model in [(LOCAL, "m-1"), (REMOTE, "m-1"), (LOCAL, "m-2")]:
        fake = Fake()
        c = client_for(provider(fake, url, model=model, key_env="K", env=env), tmp_path)
        c.chat(user("same"))
        keys.add((url, model))
        assert len(fake.requests) == 1  # a different endpoint or model is never a cache hit
    assert len(keys) == 3


def test_client_order_unchanged(tmp_path: Path) -> None:
    fake = Fake()
    c = client_for(provider(fake), tmp_path, budget=1)
    assert not c.chat(user("a")).cached
    assert c.chat(user("a")).cached  # cache hit: no send, no quota
    assert len(fake.requests) == 1 and c.quota.used("openai") == 1


def test_params_hold_no_key_and_name_the_endpoint() -> None:
    prov = provider(Fake(), REMOTE, key_env="K", env={"K": SENTINEL})
    assert prov.params == {"base_url": REMOTE, "temperature": 0.0, "json_mode": "json_schema"}
    assert prov.key_env == "K"  # only the variable's name is kept on the provider
    assert all(SENTINEL not in str(v) for k, v in vars(prov).items() if k != "_env")


@pytest.mark.parametrize(
    ("kw", "match"),
    [
        ({"base_url": "ftp://x"}, "http"),
        ({"model": ""}, "versioned"),
        ({"model": "gpt-latest"}, "versioned"),
        ({"json_mode": "xml"}, "JSON mode"),
        ({"base_url": REMOTE}, "API key"),  # non-local without a key
    ],
)
def test_config_errors(kw: dict[str, Any], match: str) -> None:
    base_url = kw.pop("base_url", LOCAL)
    with pytest.raises(OpenAICompatConfigError, match=match):
        provider(Fake(), base_url, **kw)


def test_is_local() -> None:
    assert is_local(LOCAL) and is_local("http://127.0.0.1:1234/v1")
    assert not is_local(REMOTE) and not is_local(GROQ_BASE_URL)


def _env(tmp_path: Path, **kw: str) -> dict[str, str]:
    return {"DLENS_CACHE_DIR": str(tmp_path / "c"), "DLENS_STATE_DIR": str(tmp_path / "s"), **kw}


def test_make_client_local_openai_needs_no_budget(tmp_path: Path) -> None:
    c = make_client(
        "openai", _env(tmp_path, DLENS_OPENAI_BASE_URL=LOCAL, DLENS_OPENAI_MODEL="qwen3:4b")
    )
    assert isinstance(c.provider, OpenAICompatProvider) and c.provider.local
    assert c.quota.budgets["openai"] is None


def test_make_client_remote_without_budget_is_refused(tmp_path: Path) -> None:
    env = _env(tmp_path, DLENS_OPENAI_BASE_URL=REMOTE, DLENS_OPENAI_MODEL="m-1",
               DLENS_OPENAI_KEY_ENV="MY_KEY", MY_KEY=SENTINEL)  # fmt: skip
    with pytest.raises(OpenAICompatConfigError, match="DLENS_OPENAI_DAILY_BUDGET") as e:
        make_client("openai", env)
    assert SENTINEL not in str(e.value)
    c = make_client("openai", {**env, "DLENS_OPENAI_DAILY_BUDGET": "50", "DLENS_OPENAI_RPM": "20"})
    assert c.quota.budgets["openai"] == 50 and c.limiter.rpm == 20


def test_groq_preset(tmp_path: Path) -> None:
    env = _env(tmp_path, DLENS_GROQ_MODEL="openai/gpt-oss-120b", GROQ_API_KEY=SENTINEL)
    with pytest.raises(OpenAICompatConfigError, match="GROQ_DAILY_BUDGET"):
        make_client("groq", env)
    c = make_client("groq", {**env, "GROQ_DAILY_BUDGET": "900"})
    prov = c.provider
    assert isinstance(prov, OpenAICompatProvider)
    assert (prov.name, prov.base_url, prov.key_env) == ("groq", GROQ_BASE_URL, "GROQ_API_KEY")
    assert c.limiter.rpm == 30 and c.quota.budgets["groq"] == 900
    with pytest.raises(OpenAICompatConfigError, match="API key"):
        make_client("groq", {**env, "GROQ_API_KEY": "", "GROQ_DAILY_BUDGET": "900"})


# -- key safety (owner amendment A1) ---------------------------------------------------------


def test_api_key_never_leaks(tmp_path: Path) -> None:
    """The key value reaches only the Authorization header: never params, cache keys or entries,
    the quota file, a run record, or any raised message (error paths included)."""
    env = {"MY_KEY": SENTINEL}
    ok = Fake(completion('{"answer_text": "x"}'))
    prov = provider(ok, REMOTE, key_env="MY_KEY", env=env)
    c = client_for(prov, tmp_path)
    resp = c.chat(user("q"), None, SCHEMA)
    assert ok.requests[0].headers["authorization"] == f"Bearer {SENTINEL}"
    assert c.chat(user("q"), None, SCHEMA).cached

    messages: list[str] = []
    for status in (401, 429, 500):
        bad = provider(Fake((status, f"bad key {SENTINEL[:4]}")), REMOTE, key_env="MY_KEY", env=env)
        with pytest.raises(ProviderError) as e:
            client_for(bad, tmp_path).chat(user(f"err {status}"))
        messages += [str(e.value), repr(e.value), repr(e.value.__context__)]
    down = provider(Fake(exc=httpx.ConnectError("down")), REMOTE, key_env="MY_KEY", env=env)
    with pytest.raises(ProviderError) as e:
        client_for(down, tmp_path).chat(user("err conn"))
    messages += [str(e.value), repr(e.value)]

    record = RunRecord(
        run_id="r", started_at="2026-10-20T00:00:00+00:00", question="q",
        provider=prov.name, model=prov.model, params=dict(prov.params),
        steps=[Step(index=0, phase="answer", text=resp.text)],
    )  # fmt: skip
    path = RunLogger(tmp_path / "runs").write(record)
    manifest = tmp_path / "runs" / "x.manifest.json"
    manifest.write_text(json.dumps({"provider": prov.name, "params": prov.params}))

    files = [*tmp_path.rglob("*.sqlite"), path, manifest]
    assert len(files) >= 4
    for f in files:
        assert SENTINEL.encode() not in f.read_bytes(), f.name
    for m in messages:
        assert SENTINEL not in m
    assert SENTINEL not in json.dumps(prov.params) and SENTINEL not in repr(prov)
