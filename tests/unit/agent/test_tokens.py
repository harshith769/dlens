import pytest

from dlens.agent.llm.tokens import MAX_INPUT_TOKENS, estimate_tokens
from dlens.agent.llm.types import InputTooLarge, ToolSpec

from .conftest import user


def test_small_ok_and_big_over():
    assert estimate_tokens(user("hello")) < 100
    assert estimate_tokens(user("x" * 9000)) > MAX_INPUT_TOKENS


def test_tools_count():
    t = [ToolSpec(name="t", description="d" * 3000)]
    assert estimate_tokens(user("hi"), t) > estimate_tokens(user("hi"))


def test_boundary(make):
    client, prov = make()
    ok = "x" * 8800  # ~2933 tokens plus JSON overhead stays under the cap
    assert estimate_tokens(user(ok)) <= MAX_INPUT_TOKENS
    client.chat(user(ok))
    with pytest.raises(InputTooLarge):
        client.chat(user("x" * 9100))
    assert prov.calls == 1
