from types import SimpleNamespace as NS

import pytest

from dlens.agent.llm.ollama import OllamaProvider, strip_think
from dlens.agent.llm.types import Message, ProviderError, ToolSpec

from .conftest import user


class FakeOllama:
    def __init__(self, message, err=None):
        self.message, self.err, self.kwargs = message, err, None

    def chat(self, **kwargs):
        self.kwargs = kwargs
        if self.err:
            raise self.err
        return NS(message=self.message, prompt_eval_count=11, eval_count=7)


def msg(content="", calls=None):
    return NS(content=content, tool_calls=calls)


def test_params_sent():
    fake = FakeOllama(msg("ok"))
    resp = OllamaProvider(client=fake).send(user("hi"), None)
    assert fake.kwargs["model"] == "qwen3:4b-instruct-2507-q4_K_M"
    assert fake.kwargs["think"] is False
    assert fake.kwargs["options"] == {"temperature": 0, "num_ctx": 8192}
    assert "tools" not in fake.kwargs
    assert (resp.text, resp.usage.input_tokens, resp.usage.output_tokens) == ("ok", 11, 7)


@pytest.mark.parametrize(
    ("raw", "want"),
    [
        ("<think>a</think>hello", "hello"),
        ("<think>\nmulti\nline\n</think>\n\nhello", "hello"),
        ("hello", "hello"),
        ("hi <think>unfinished", "hi"),
        ("reasoning</think>answer", "answer"),
        ("<think>a</think>x<think>b</think>y", "xy"),
    ],
)
def test_strip_think(raw, want):
    assert strip_think(raw) == want


def test_tool_calls_have_deterministic_ids():
    calls = [
        NS(function=NS(name="trace", arguments={"column_id": "a.b"})),
        NS(function=NS(name="impact", arguments={"column_id": "c.d"})),
    ]
    runs = [
        OllamaProvider(client=FakeOllama(msg("", calls))).send(user("q"), None) for _ in range(2)
    ]
    ids = [[c.id for c in r.tool_calls] for r in runs]
    assert ids == [["call_0", "call_1"]] * 2
    assert runs[0].tool_calls[0].arguments == {"column_id": "a.b"}


def test_tools_and_history_conversion():
    fake = FakeOllama(msg("done"))
    history = [
        Message(role="user", content="q"),
        runs := OllamaProvider(
            client=FakeOllama(msg("", [NS(function=NS(name="t", arguments={"a": 1}))]))
        )
        .send(user("q"), None)
        .as_message(),
        Message(role="tool", content="{}", tool_call_id="call_0", name="t"),
    ]
    assert runs.tool_calls[0].id == "call_0"
    OllamaProvider(client=fake).send(history, [ToolSpec(name="t", description="d")])
    sent = fake.kwargs
    assert sent["tools"][0]["function"]["name"] == "t"
    assert sent["messages"][1]["tool_calls"][0]["function"]["arguments"] == {"a": 1}
    assert sent["messages"][2]["tool_name"] == "t"


def test_error_maps_to_provider_error():
    err = type("E", (Exception,), {"status_code": 503})("busy")
    with pytest.raises(ProviderError) as ei:
        OllamaProvider(client=FakeOllama(None, err)).send(user("hi"), None)
    assert ei.value.status_code == 503
    assert ei.value.retryable is True
