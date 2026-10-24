"""The app in project mode (``dlens ui --project``, S14 E2) on an artifact-ingested copy of the
eph_shop fixture. The LLM is a scripted stub; no real provider is ever called.

Checks: the five tabs and the privacy line, the no-LLM tabs, Ask through the S4 agent and
validator (removed claims visible), the not-ingested state, isolation of Ask's files from the
benchmark, and that a sentinel key never shows up in state, output, logs or caches."""

import json
import shutil
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

pytest.importorskip("streamlit", reason="needs the ui extra: uv sync --extra ui")
from streamlit.testing.v1 import AppTest  # noqa: E402

import dlens.agent.llm as llm  # noqa: E402
from dlens.agent.llm.base import LLMClient  # noqa: E402
from dlens.agent.llm.cache import ResponseCache  # noqa: E402
from dlens.agent.llm.config import cache_path, quota_path  # noqa: E402
from dlens.agent.llm.quota import QuotaCounter, default_budgets  # noqa: E402
from dlens.agent.llm.ratelimit import RateLimiter  # noqa: E402
from dlens.agent.llm.types import ProviderError  # noqa: E402
from dlens.agent.tools.provenance import edge_id  # noqa: E402
from dlens.graph import load_or_build_artifacts  # noqa: E402
from dlens.ui import project as proj  # noqa: E402
from dlens.ui import view  # noqa: E402

from ..loop.conftest import ScriptedProvider, call, done, draft  # noqa: E402

APP = str(view.ROOT / "src/dlens/ui/app.py")
EPH = Path(__file__).parents[3] / "fixtures" / "artifacts" / "eph_shop"
EVAL = view.ROOT / "eval"
SENTINEL = "AIzaSENTINEL-key-0123456789"


@pytest.fixture
def eph(tmp_path: Path) -> Path:
    dest = tmp_path / "eph_shop"
    shutil.copytree(EPH, dest, symlinks=True)
    return dest


@pytest.fixture
def home(tmp_path: Path, monkeypatch) -> Path:
    """A fresh HOME with no XDG overrides: anything written to the default dlens paths shows."""
    h = tmp_path / "home"
    h.mkdir()
    monkeypatch.setenv("HOME", str(h))
    for var in (
        "XDG_CACHE_HOME",
        "XDG_STATE_HOME",
        "DLENS_CACHE_DIR",
        "DLENS_STATE_DIR",
        "DLENS_RUN_DIR",
        "DLENS_DEMO",
    ):
        monkeypatch.delenv(var, raising=False)
    return h


@pytest.fixture
def start(eph: Path, home: Path, monkeypatch):
    """``start(script, ingest=True)`` -> a rendered AppTest in project mode on ``eph``."""
    import streamlit as st

    envs: list[dict[str, str]] = []

    def _start(script, ingest: bool = True):
        st.cache_resource.clear()
        if ingest:
            load_or_build_artifacts(eph / "target")
        for k, v in proj.launch_env(proj.locate(eph)).items():
            monkeypatch.setenv(k, v)
        prov = ScriptedProvider(script)

        def fake_make_client(provider=None, env=None):
            # The real client wiring, paths from the env the UI built; only the provider is fake.
            envs.append(dict(env or {}))
            return LLMClient(
                prov,
                ResponseCache(cache_path(env)),
                QuotaCounter(quota_path(env), default_budgets(env)),
                RateLimiter(None),
            )

        monkeypatch.setattr(llm, "make_client", fake_make_client)
        at = AppTest.from_file(APP, default_timeout=30)
        at.run()
        at.provider, at.envs = prov, envs
        return at

    return _start


def _graph(eph: Path):
    return load_or_build_artifacts(eph / "target").graph


def _answer(eph: Path, bogus: bool = False):
    """Trace customer_summary.customer_id, cite its edge; ``bogus`` adds an uncited claim."""
    g = _graph(eph)
    e = next(e for e in g.edges() if e.to_column.endswith("customer_summary.customer_id"))
    claims = [
        (f"customer_summary.customer_id comes from {g.display_name(e.from_column)}", [edge_id(e)])
    ]
    if bogus:
        claims.append(("customer_summary.customer_id is a hash of the email", ["e_nope"]))
    answer = draft("customer_id is passed through.", claims)
    # a failing claim makes the agent regenerate the draft once (the same draft again here)
    return [call("trace_upstream", column_id="customer_summary.customer_id"), done(), answer] + (
        [answer] if bogus else []
    )


def texts(at) -> list[str]:
    return [m.value for m in at.markdown]


def everything(at) -> str:
    """All text the app rendered, every kind of element."""
    parts: list[str] = []
    for kind in ("markdown", "caption", "code", "error", "warning", "info", "exception"):
        parts += [str(getattr(el, "value", "")) for el in at.get(kind)]
    parts += [h.proto.body for h in at.get("html")]
    for t in at.text_input:
        # the element protos are what goes to the browser; a password box's own value is the
        # user's input, held by Streamlit as widget state (not in st.session_state)
        parts.append(str(t.proto))
        if t.proto.type != t.proto.PASSWORD:
            parts.append(str(t.value))
    return "\n".join(parts)


def ask(at, question="Where does customer_summary.customer_id come from?"):
    at.text_area(key="question").set_value(question).run()
    next(b for b in at.button if b.label == "Ask").click().run()
    assert not at.exception, at.exception
    return at


def pick_gemini(at, key: str = "", key_env: str = ""):
    at.radio(key="ui_provider").set_value("gemini").run()
    box = next(t for t in at.text_input if t.label.startswith("Gemini key"))
    box.set_value(key)
    at.text_input(key="ui_gemini_key_env").set_value(key_env)
    at.run()
    return at


def tree(root: Path) -> dict[str, float]:
    return {str(p): p.stat().st_mtime for p in root.rglob("*") if "__pycache__" not in p.parts}


# -- layout and the no-LLM tabs -------------------------------------------------------------------


def test_five_tabs_privacy_line_and_no_llm_tabs(start, eph: Path) -> None:
    at = start([])
    assert not at.exception and not at.error
    assert [t.label for t in at.tabs][:5] == [
        "Explore",
        "Trace / Impact",
        "Source",
        "Ask",
        "How it works",
    ]
    assert proj.PRIVACY in [c.value for c in at.caption]
    folder = proj.locate(eph).folder
    assert any("<b>eph_shop</b> · 7 models" in t and folder in t for t in texts(at))
    assert at.selectbox(key="trace_col").value == "customer_names.customer_id"  # has lineage
    assert any("--artifacts target --depth 3` in the project folder" in c.value for c in at.caption)
    assert {m.label: m.value for m in at.metric}["FULL"] == "7"
    models = next(f.value for f in at.dataframe if "Parse" in f.value.columns)
    assert "customer_summary" in list(models["Model"])
    # Trace / Impact
    at.selectbox(key="trace_col").set_value("customer_summary.customer_id").run()
    assert any("dlens trace customer_summary.customer_id" in c.value for c in at.caption)
    assert at.get("graphviz_chart")
    at.segmented_control(key="trace_dir").set_value("Impact (downstream)").run()
    assert not at.exception
    # Source: graph files only, as written and compiled
    at.selectbox(key="src_file").set_value("models/customer_summary.sql").run()
    src = [h.proto.body for h in at.get("html") if 'class="dl-src"' in h.proto.body]
    assert src and "ref" in src[-1]
    at.segmented_control(key="src_kind").set_value("Compiled").run()
    assert any("compiled/eph_shop/models/customer_summary.sql" in t for t in texts(at))
    assert at.provider.requests == [] and at.envs == []  # no model was even built


def test_not_ingested_shows_the_command_and_the_privacy_line(start, eph: Path) -> None:
    at = start([], ingest=False)
    assert not at.exception
    assert any("not ingested yet" in e.value for e in at.error)
    assert "dlens ingest --artifacts target" in [c.value for c in at.code]
    assert proj.PRIVACY in [c.value for c in at.caption]
    assert not at.tabs


# -- Ask ------------------------------------------------------------------------------------------


def test_ask_runs_the_agent_and_shows_removed_claims(start, eph: Path) -> None:
    at = ask(start(_answer(eph, bogus=True)))
    assert not at.error, [e.value for e in at.error]
    assert any("Partially removed" in t for t in texts(at))
    assert any("✓" in t and "comes from stg_customers.customer_id" in t for t in texts(at))
    assert any("Removed by the validator (1)" in e.label for e in at.expander)
    assert any("is a hash of the email · failed R2" in t for t in texts(at))
    run = at.session_state.run
    assert run.record.validation and not run.record.validation.get("skipped")
    assert len(at.provider.requests) == 4


def test_ask_files_live_under_target_dlens_ui_and_never_in_eval(
    start, eph: Path, home: Path
) -> None:
    before = tree(EVAL)
    at = ask(start(_answer(eph)))
    assert not at.error, [e.value for e in at.error]
    assert tree(EVAL) == before
    assert not (home / ".cache").exists() and not (home / ".local").exists()
    ui = eph.resolve() / "target" / "dlens" / "ui"
    assert (ui / "cache" / "llm.sqlite").is_file()
    assert (ui / "state" / "quota.sqlite").is_file()
    assert list((ui / "runs").glob("*.jsonl"))
    [env] = at.envs
    assert env["DLENS_PROVIDER"] == "ollama" and "GEMINI_API_KEY" not in env


def test_ambient_gemini_key_is_never_used(start, eph: Path, monkeypatch) -> None:
    if proj.missing_extra("gemini") is not None:
        pytest.skip("needs the agent extra")
    monkeypatch.setenv("GEMINI_API_KEY", SENTINEL)
    at = ask(pick_gemini(start(_answer(eph))))
    assert any("No Gemini key" in e.value for e in at.error)
    assert at.envs == [] and at.provider.requests == []
    assert SENTINEL not in everything(at)


def test_named_env_var_key_is_used_but_never_shown(start, eph: Path, monkeypatch) -> None:
    if proj.missing_extra("gemini") is not None:
        pytest.skip("needs the agent extra")
    monkeypatch.setenv("MY_GEMINI_KEY", SENTINEL)
    at = pick_gemini(start(_answer(eph)), key_env="MY_GEMINI_KEY")
    assert any("Using the key in $MY_GEMINI_KEY." in c.value for c in at.caption)
    assert any("never saved" in c.value for c in at.caption)
    ask(at)
    assert at.envs[0]["GEMINI_API_KEY"] == SENTINEL
    assert at.envs[0]["GEMINI_DAILY_BUDGET"] == "50"
    assert SENTINEL not in everything(at)


def _leaks(at, eph: Path, home: Path) -> list[str]:
    """Every place the sentinel shows up: rendered output, the user session state, any file."""
    found = []
    if SENTINEL in everything(at):
        found.append("rendered output")
    state = at.session_state._state  # the SessionState behind st.session_state
    dump = {k: state[k] for k in state.filtered_state}
    if SENTINEL in repr(dump):
        found.append("session_state")
    if SENTINEL in json.dumps({k: repr(v) for k, v in dump.items()}):
        found.append("session_state json")
    for root in (eph, home):
        for p in root.rglob("*"):
            if p.is_file() and SENTINEL.encode() in p.read_bytes():
                found.append(str(p))
    return found


def test_sentinel_key_never_leaks_on_a_good_answer(start, eph: Path, home: Path) -> None:
    if proj.missing_extra("gemini") is not None:
        pytest.skip("needs the agent extra")
    at = ask(pick_gemini(start(_answer(eph)), key=SENTINEL))
    assert not at.error, [e.value for e in at.error]
    assert at.envs[0]["GEMINI_API_KEY"] == SENTINEL  # the key did reach the client
    assert any("customer_id is passed through." in t for t in texts(at))
    assert _leaks(at, eph, home) == []


def test_sentinel_key_echoed_by_the_provider_is_redacted(start, eph: Path, home: Path) -> None:
    if proj.missing_extra("gemini") is not None:
        pytest.skip("needs the agent extra")
    echo = ProviderError(f"gemini call failed: 400 API key not valid: {SENTINEL}")
    at = ask(pick_gemini(start([echo]), key=SENTINEL))
    assert any("call failed" in e.value and "[redacted]" in e.value for e in at.error)
    assert _leaks(at, eph, home) == []


def test_sentinel_key_in_an_exception_is_redacted(start, eph: Path, home: Path) -> None:
    if proj.missing_extra("gemini") is not None:
        pytest.skip("needs the agent extra")
    at = start([RuntimeError(f"boom {SENTINEL}")])
    at = ask(pick_gemini(at, key=SENTINEL))
    assert _leaks(at, eph, home) == []


# -- without the agent and retrieval extras -------------------------------------------------------

NO_EXTRAS = textwrap.dedent(
    """
    import importlib.abc, sys
    BLOCK = {"ollama", "google.genai", "httpx", "bm25s", "onnxruntime", "tokenizers"}

    def blocked(name):
        return any(name == b or name.startswith(b + ".") for b in BLOCK)

    class Block(importlib.abc.MetaPathFinder):
        def find_spec(self, name, path=None, target=None):
            if blocked(name):
                raise ModuleNotFoundError(f"No module named {name!r} (blocked)")
            return None

    sys.meta_path.insert(0, Block())
    from streamlit.testing.v1 import AppTest
    at = AppTest.from_file(sys.argv[1], default_timeout=60)
    at.run()
    assert not at.exception, at.exception
    at.selectbox(key="trace_col").set_value("customer_summary.customer_id").run()
    at.selectbox(key="src_file").set_value("models/customer_summary.sql").run()
    at.text_area(key="question").set_value("Where does customer_id come from?").run()
    next(b for b in at.button if b.label == "Ask").click().run()
    assert not at.exception, at.exception
    print("TABS", [t.label for t in at.tabs])
    print("METRICS", {m.label: m.value for m in at.metric})
    print("GRAPHS", len(at.get("graphviz_chart")))
    print("SRC", any('class="dl-src"' in h.proto.body for h in at.get("html")))
    print("ERRORS", [e.value for e in at.error])
    print("CAPTIONS", [c.value for c in at.caption])
    print("LOADED", sorted(m for m in sys.modules if blocked(m)))
    """
)


def test_no_llm_tabs_work_without_agent_or_retrieval_extras(eph: Path, tmp_path: Path) -> None:
    load_or_build_artifacts(eph / "target")
    script = tmp_path / "no_extras.py"
    script.write_text(NO_EXTRAS)
    env = {**proj.launch_env(proj.locate(eph)), "HOME": str(tmp_path / "home")}
    import os

    env["PATH"] = os.environ.get("PATH", "")
    out = subprocess.run(
        [sys.executable, "-I", str(script), APP],
        capture_output=True,
        text=True,
        env=env,
        timeout=180,
    )
    assert out.returncode == 0, out.stderr[-3000:]
    lines = dict(line.split(" ", 1) for line in out.stdout.splitlines() if " " in line)
    assert "'Explore', 'Trace / Impact', 'Source', 'Ask', 'How it works'" in lines["TABS"]
    assert "'FULL': '7'" in lines["METRICS"]
    assert int(lines["GRAPHS"]) >= 1 and lines["SRC"] == "True"
    assert "Ask needs the agent extra" in lines["ERRORS"]
    assert "retrieval extra is not installed" in lines["CAPTIONS"]
    assert lines["LOADED"] == "[]"
