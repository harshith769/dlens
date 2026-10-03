from dlens.agent.llm.cache import ResponseCache, cache_key
from dlens.agent.llm.types import LLMResponse, Message, ToolCall, ToolSpec

M = [Message(role="user", content="hi")]
T = [ToolSpec(name="t", description="d")]


def key(**over):
    args = dict(provider="p", model="m", messages=M, tools=T, params={"a": 1, "b": 2})
    args.update(over)
    return cache_key(**args)


def test_key_is_stable_and_order_independent():
    assert key() == key(params={"b": 2, "a": 1})


def test_key_changes_with_each_input():
    base = key()
    variants = [
        key(provider="q"),
        key(model="n"),
        key(messages=[Message(role="user", content="yo")]),
        key(tools=None),
        key(params={"a": 1, "b": 3}),
    ]
    assert len({base, *variants}) == 6


def test_roundtrip_persists_tool_calls_and_provider_meta(tmp_path):
    resp = LLMResponse(
        text="x",
        tool_calls=[
            ToolCall(
                id="call_0",
                name="t",
                arguments={"k": [1]},
                provider_meta={"thought_signature": "c2ln"},
            )
        ],
        cached=True,
    )
    ResponseCache(tmp_path / "c.sqlite").put("k", resp)
    got = ResponseCache(tmp_path / "c.sqlite").get("k")  # new instance = new connection
    assert got is not None
    assert got.tool_calls == resp.tool_calls
    assert got.tool_calls[0].provider_meta == {"thought_signature": "c2ln"}
    assert got.cached is False  # stored form never claims to be a hit
    assert ResponseCache(tmp_path / "c.sqlite").get("missing") is None


SCHEMA = {"type": "object", "properties": {"a": {"type": "string"}}}


def test_response_schema_is_part_of_the_key():
    assert key(response_schema=SCHEMA) != key()
    assert key(response_schema=SCHEMA) != key(response_schema={"type": "object"})


def test_no_schema_keeps_the_pre_schema_key():
    """Entries cached before response_schema existed must still hit."""
    import hashlib
    import json

    legacy = json.dumps(
        {
            "provider": "p",
            "model": "m",
            "messages": [m.model_dump(mode="json") for m in M],
            "tools": [t.model_dump(mode="json") for t in T],
            "params": {"a": 1, "b": 2},
        },
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    )
    assert key(response_schema=None) == hashlib.sha256(legacy.encode()).hexdigest()
