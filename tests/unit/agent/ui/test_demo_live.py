"""Demo mode's live questions: Gemini behind the caps (50 calls/day app-wide, 5 per session,
300 characters). The provider is a scripted fake inside a real LLMClient whose quota counter is
the demo's own file, so the header count and the gate read exactly what the client wrote."""

import shutil
from datetime import datetime

import pytest

from dlens.agent.llm.base import LLMClient
from dlens.agent.llm.cache import ResponseCache
from dlens.agent.llm.config import cache_path, quota_path
from dlens.agent.llm.quota import PACIFIC, QuotaCounter
from dlens.agent.llm.ratelimit import RateLimiter
from dlens.agent.llm.types import QuotaExceeded
from dlens.ui import demo

from ..loop.conftest import ScriptedProvider, call, done, draft

SECRET = "AIza-test-not-a-real-key-7f3a9"
QUESTION = "Where does stg_payments.amount_usd come from?"


# -- pure helpers --------------------------------------------------------------------------------


def test_gate_order_and_messages():
    ok = "x" * demo.MAX_QUESTION_CHARS
    assert demo.gate(ok, 0, 50) is None
    assert demo.gate(ok, 4, demo.CALLS_PER_QUESTION) is None
    assert demo.gate(ok, 0, 50, key=False)[0] == "Live questions are off"
    assert demo.gate(ok + "y", 0, 50)[0] == "Question too long"
    title, body = demo.gate(ok, 5, 50)
    assert title == "Demo limit reached" and "preset" in body and "5 live questions" in body
    title, body = demo.gate(ok, 0, demo.CALLS_PER_QUESTION - 1)
    assert title == "Demo limit reached" and "50 model calls" in body


def test_failure_maps_quota_and_provider_errors_only():
    assert demo.failure("QuotaExceeded: gemini: daily budget of 50 calls used up")[0] == (
        "Demo limit reached"
    )
    assert "unavailable" in demo.failure("ProviderError: gemini call failed (429): busy")[0]
    assert demo.failure("Column foo.bar does not exist") is None
    assert demo.failure(None) is None


def test_client_env_uses_demo_budget_and_demo_only_dirs(tmp_path):
    base = {"DLENS_STATE_DIR": "/dev-state", "GEMINI_DAILY_BUDGET": "400", "HOME": "/h"}
    env = demo.client_env(
        {**base, "DLENS_DEMO_STATE_DIR": str(tmp_path)},
        {"GEMINI_API_KEY": SECRET, "DLENS_GEMINI_MODEL": "gemini-x-001", "OTHER": "no"},
    )
    assert env["GEMINI_DAILY_BUDGET"] == "50" and env["GEMINI_API_KEY"] == SECRET
    assert env["DLENS_GEMINI_MODEL"] == "gemini-x-001" and "OTHER" not in env
    assert quota_path(env).parent == tmp_path and "/dev-state" not in str(quota_path(env))
    assert cache_path(env).is_relative_to(tmp_path)
    assert demo.state_dir({}).name == "dlens-demo"


def test_calls_left_reads_the_demo_counter(tmp_path):
    env = demo.client_env({"DLENS_DEMO_STATE_DIR": str(tmp_path)}, {})
    assert demo.calls_left(env) == 50
    counter = QuotaCounter(quota_path(env), {"gemini": 50})
    for _ in range(3):
        counter.reserve("gemini")
    assert demo.calls_left(env) == 47


# -- the app -------------------------------------------------------------------------------------

pytest.importorskip("streamlit", reason="needs the ui extra: uv sync --extra ui")


class FakeGemini(ScriptedProvider):
    name = "gemini"
    model = "gemini-fake-001"


def _answer():
    from dlens.agent.tools.provenance import edge_id

    graph = demo.load_graph(demo.projects({})[demo.PROJECT])
    edge = next(e for e in graph.edges() if e.to_column.endswith("stg_payments.amount_usd"))
    return [
        call("trace_upstream", column_id="stg_payments.amount_usd"),
        done(),
        draft("amount_usd renames raw_payments.amt.", [("renamed from amt", [edge_id(edge)])]),
    ]


@pytest.fixture
def live(monkeypatch, tmp_path):
    """``live(script, secrets=..., used=0)`` -> (AppTest in demo mode, fake provider, made)."""
    import streamlit as st
    from streamlit.testing.v1 import AppTest

    import dlens.agent.llm as llm

    st.cache_resource.clear()
    copy = tmp_path / "bundle"
    shutil.copytree(demo.ROOT / "demo", copy)
    monkeypatch.setenv("DLENS_DEMO", "1")
    monkeypatch.setenv("DLENS_DEMO_DIR", str(copy))
    monkeypatch.setenv("DLENS_DEMO_STATE_DIR", str(tmp_path / "state"))
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    made: list[dict[str, str]] = []

    def _start(script, secrets=None, used=0):
        prov = FakeGemini(script)
        env = demo.client_env({"DLENS_DEMO_STATE_DIR": str(tmp_path / "state")}, {})
        counter = QuotaCounter(quota_path(env), {"gemini": 50})
        for _ in range(used):
            counter.reserve("gemini")

        def fake_make_client(provider=None, env=None):
            assert provider == "gemini" and env is not None
            made.append(dict(env))
            return LLMClient(
                prov,
                ResponseCache(cache_path(env)),
                QuotaCounter(
                    quota_path(env),
                    {"gemini": int(env["GEMINI_DAILY_BUDGET"])},
                    lambda: datetime.now(PACIFIC),
                ),
                RateLimiter(None),
            )

        monkeypatch.setattr(llm, "make_client", fake_make_client)
        at = AppTest.from_file(str(demo.ROOT / "src/dlens/ui/app.py"), default_timeout=30)
        at.secrets.update({"GEMINI_API_KEY": SECRET} if secrets is None else secrets)
        at.run()
        return at, prov, made

    return _start


def _slot(at):
    return next(m.value for m in at.markdown if "Gemini Flash-Lite (demo)" in m.value)


def _ask(at, question=QUESTION):
    at.text_area(key="question").set_value(question).run()
    next(b for b in at.button if b.label == "Ask").click().run()
    assert not at.exception, at.exception
    return at


def _warnings(at):
    return [w.value for w in at.warning]


def test_header_shows_calls_left_today(live):
    at, _, _ = live([], used=4)
    assert not at.exception and not at.error
    assert "46 of 50 left today" in _slot(at)


def test_live_question_answers_and_spends_demo_quota(live):
    at, prov, _ = live(_answer())
    _ask(at)
    assert not at.error and not _warnings(at)
    assert at.session_state.run is not None and at.session_state.live_asked == 1
    assert at.session_state.run.record.provider == "gemini"
    assert f"{50 - len(prov.requests)} of 50 left today" in _slot(at)


def test_sixth_live_question_in_a_session_hits_the_limit(live):
    at, prov, _ = live(_answer())
    for _ in range(demo.SESSION_QUESTIONS):  # the repeats are cache hits: no new requests
        _ask(at)
        assert not _warnings(at)
    sent = len(prov.requests)
    _ask(at)
    assert any("Demo limit reached" in w and "preset" in w for w in _warnings(at))
    assert len(prov.requests) == sent and at.session_state.run is None


def test_daily_budget_too_low_for_a_full_run_blocks_before_any_call(live):
    at, prov, made = live(_answer(), used=50 - demo.CALLS_PER_QUESTION + 1)
    _ask(at)
    assert any("50 model calls" in w for w in _warnings(at))
    assert prov.requests == [] and made == []


def test_quota_exceeded_mid_run_is_the_limit_state(live):
    at, prov, _ = live([QuotaExceeded("gemini: daily budget of 50 calls used up")])
    _ask(at)
    assert any("Demo limit reached" in w for w in _warnings(at))
    assert not at.error and at.session_state.run is None


def test_no_key_turns_live_questions_off(live):
    at, prov, made = live(_answer(), secrets={})
    assert "live questions off" in _slot(at)
    _ask(at)
    assert any("Live questions are off" in w for w in _warnings(at))
    assert prov.requests == [] and made == []


def test_key_comes_from_secrets_and_is_never_shown_or_logged(live, tmp_path):
    at, _, made = live(_answer())
    _ask(at)
    assert made and made[0]["GEMINI_API_KEY"] == SECRET
    shown = [m.value for m in at.markdown] + [str(c.value) for c in at.code]
    assert not any(SECRET in s for s in shown)
    logs = list((tmp_path / "state" / "runs").rglob("*.jsonl"))
    assert logs and not any(SECRET in p.read_text() for p in logs)
    assert not any(
        SECRET in p.read_text(errors="replace") for p in (tmp_path / "state").rglob("*.json*")
    )
