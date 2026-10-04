"""scripts/smoke_agent.py --provider gemini: guards, the hard cap and the per-question report,
with a fake provider (no network). Runs the real loop and validator on the demo bundle."""

import importlib.util
import json
from pathlib import Path

import pytest

from dlens.agent.llm.base import LLMClient
from dlens.agent.llm.cache import ResponseCache
from dlens.agent.llm.config import cache_path, quota_path
from dlens.agent.llm.quota import QuotaCounter
from dlens.agent.llm.ratelimit import RateLimiter
from dlens.agent.llm.types import LLMResponse

ROOT = Path(__file__).parents[3]
_spec = importlib.util.spec_from_file_location("smoke_agent", ROOT / "scripts" / "smoke_agent.py")
assert _spec and _spec.loader
smoke = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(smoke)


class FakeGemini:
    """Ends the tool phase at once and drafts an answer without claims."""

    name = "gemini"
    model = "gemini-fake-001"
    params: dict = {}

    def __init__(self):
        self.sent = 0

    def send(self, messages, tools, response_schema=None):
        self.sent += 1
        if response_schema is not None:
            body = {"answer_text": "No.", "claims": [], "confidence": "low", "refused": False}
            return LLMResponse(text=json.dumps(body))
        return LLMResponse(text="I have enough evidence.")


@pytest.fixture
def env(tmp_path, monkeypatch):
    monkeypatch.setenv("DLENS_DEMO_STATE_DIR", str(tmp_path / "demo-state"))
    return {
        "DLENS_STATE_DIR": str(tmp_path / "dev-state"),
        "DLENS_CACHE_DIR": str(tmp_path / "cache"),
        "DLENS_RUN_DIR": str(tmp_path / "runs"),
        "GEMINI_DAILY_BUDGET": "400",
    }


@pytest.fixture
def factory():
    made = []

    def _make(provider, env):
        assert provider == "gemini"
        prov = FakeGemini()
        made.append((prov, dict(env)))
        return LLMClient(
            prov,
            ResponseCache(cache_path(env)),
            QuotaCounter(quota_path(env), {"gemini": int(env["GEMINI_DAILY_BUDGET"])}),
            RateLimiter(None),
        )

    _make.made = made
    return _make


def test_refused_without_the_spend_flag(env):
    with pytest.raises(SystemExit, match="--yes-spend-quota"):
        smoke.main(["--provider", "gemini", "--max-calls", "16"], env)


@pytest.mark.parametrize("n", [None, "0", "17"])
def test_max_calls_must_be_within_the_hard_cap(env, n):
    argv = ["--provider", "gemini", "--yes-spend-quota"] + (["--max-calls", n] if n else [])
    with pytest.raises(SystemExit, match="between 1 and 16"):
        smoke.main(argv, env)


def test_runs_both_questions_and_reports_each(env, factory, capsys):
    # the fake drafts no claims, so dev-01 cannot pass the dev scoring: exit 1
    assert smoke.smoke_gemini(16, env, factory) == 1
    prov, used_env = factory.made[0]
    out = capsys.readouterr().out
    assert "quota before: used today 0, left 400 of 400" in out
    assert "[dev-01] Where does stg_payments.amount_usd come from?" in out
    assert "[dev-10] If raw_payments.amt changes" in out
    assert out.count("verdict=") == 2 and out.count("validation=") == 2
    assert out.count("calls=") == 2 and "dev_pass=" in out
    assert 0 < prov.sent <= 16
    assert f"live calls sent: {prov.sent} (cap 16)" in out
    assert f"quota after:  used today {prov.sent}, left {400 - prov.sent} of 400" in out
    assert quota_path(used_env) == quota_path(env)  # the DEV counter
    assert "FAILED: dev pass 1/2" in out


def test_question_that_cannot_fit_under_the_cap_is_not_started(env, factory, capsys):
    assert smoke.smoke_gemini(8, env, factory) == 1
    prov, _ = factory.made[0]
    out = capsys.readouterr().out
    assert prov.sent <= 8
    assert "[dev-10] not run" in out or prov.sent == 0


def test_refuses_when_budget_left_is_below_max_calls(env, factory, capsys):
    env = {**env, "GEMINI_DAILY_BUDGET": "10"}
    assert smoke.smoke_gemini(16, env, factory) == 2
    assert factory.made[0][0].sent == 0
    assert "refused: only 10 calls left today" in capsys.readouterr().out


def test_refuses_the_demo_counter(env, factory, tmp_path):
    with pytest.raises(SystemExit, match="demo's"):
        smoke.smoke_gemini(16, {**env, "DLENS_STATE_DIR": str(tmp_path / "demo-state")}, factory)
    assert factory.made == []


def test_outcome_labels_follow_the_owner_names():
    dev = smoke._script("dev_report")
    assert smoke.OUTCOME_LABELS == {"pass": "raw", "warning": "salvaged"}
    v = {"repairs": [1]}
    assert dev.validator_outcome({}, {"validation": v}) == "repaired"
