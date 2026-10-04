"""scripts/smoke_llm.py --provider gemini: refusals, hard cap and the dev quota counter, with a
fake provider (no network)."""

import importlib.util
from pathlib import Path

import pytest

from dlens.agent.llm.base import LLMClient
from dlens.agent.llm.cache import ResponseCache
from dlens.agent.llm.config import cache_path, quota_path
from dlens.agent.llm.quota import QuotaCounter
from dlens.agent.llm.ratelimit import RateLimiter
from dlens.agent.llm.types import LLMResponse, ToolCall

ROOT = Path(__file__).parents[3]
_spec = importlib.util.spec_from_file_location("smoke_llm", ROOT / "scripts" / "smoke_llm.py")
assert _spec and _spec.loader
smoke = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(smoke)


class FakeGemini:
    name = "gemini"
    model = "gemini-fake-001"
    params: dict = {}

    def __init__(self):
        self.sent = 0

    def send(self, messages, tools, response_schema=None):
        self.sent += 1
        if tools:
            return LLMResponse(
                tool_calls=[ToolCall(id="c0", name="echo", arguments={"text": "ok"})]
            )
        return LLMResponse(text='{"word": "ok"}' if response_schema else "ok")


@pytest.fixture
def env(tmp_path, monkeypatch):
    monkeypatch.setenv("DLENS_DEMO_STATE_DIR", str(tmp_path / "demo-state"))
    return {"DLENS_STATE_DIR": str(tmp_path / "dev-state"), "GEMINI_DAILY_BUDGET": "400"}


@pytest.fixture
def factory():
    made = []

    def _make(provider, env):
        assert provider == "gemini"
        prov = FakeGemini()
        budget = int(env["GEMINI_DAILY_BUDGET"])
        client = LLMClient(
            prov,
            ResponseCache(cache_path(env)),
            QuotaCounter(quota_path(env), {"gemini": budget}),
            RateLimiter(None),
        )
        made.append((prov, dict(env)))
        return client

    _make.made = made
    return _make


def test_gemini_refused_without_the_spend_flag(env):
    with pytest.raises(SystemExit, match="--yes-spend-quota"):
        smoke.main(["--provider", "gemini", "--max-calls", "1"], env)


@pytest.mark.parametrize("n", [None, "0", "11"])
def test_gemini_needs_max_calls_within_the_hard_cap(env, n):
    argv = ["--provider", "gemini", "--yes-spend-quota"] + (["--max-calls", n] if n else [])
    with pytest.raises(SystemExit, match="between 1 and 10"):
        smoke.main(argv, env)


def test_smoke_sends_at_most_max_calls_and_prints_the_counter(env, factory, capsys):
    assert smoke.smoke_gemini(2, env, factory) == 0
    prov, used_env = factory.made[0]
    assert prov.sent == 2  # text + json; the repeat is a cache hit
    out = capsys.readouterr().out
    assert "quota before: used today 0, left 400 of 400" in out
    assert "quota after:  used today 2, left 398 of 400" in out
    assert "repeat: cached=True" in out and "OK: gemini smoke passed." in out
    # the dev counter, a throwaway cache
    assert quota_path(used_env) == quota_path(env)
    assert cache_path(used_env) != cache_path(env)


def test_all_checks_including_a_tool_call(env, factory, capsys):
    assert smoke.smoke_gemini(10, env, factory) == 0
    assert factory.made[0][0].sent == len(smoke.CHECKS) == 3
    assert "tool calls: [('echo', {'text': 'ok'})]" in capsys.readouterr().out


def test_capped_send_refuses_the_extra_call():
    capped = smoke.CappedSend(lambda *a, **k: LLMResponse(text="ok"), 1)
    capped()
    with pytest.raises(RuntimeError, match="hard cap"):
        capped()
    assert capped.calls == 1


def test_refuses_when_budget_left_is_below_max_calls(env, factory, capsys):
    counter = QuotaCounter(quota_path(env), {"gemini": 400})
    env = {**env, "GEMINI_DAILY_BUDGET": "2"}
    counter.reserve("gemini")  # 1 left of 2
    assert smoke.smoke_gemini(2, env, factory) == 2
    assert factory.made[0][0].sent == 0
    assert "refused: only 1 calls left today" in capsys.readouterr().out


def test_refuses_the_demo_counter(env, factory, tmp_path):
    demo_env = {**env, "DLENS_STATE_DIR": str(tmp_path / "demo-state")}
    with pytest.raises(SystemExit, match="demo's"):
        smoke.smoke_gemini(1, demo_env, factory)
    assert factory.made == []
