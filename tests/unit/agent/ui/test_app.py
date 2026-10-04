"""Smoke tests of the Streamlit app with a scripted fake client (no Ollama, no dbt)."""

from pathlib import Path

import pytest

pytest.importorskip("streamlit", reason="needs the ui extra: uv sync --extra ui")
from streamlit.testing.v1 import AppTest  # noqa: E402

import dlens.agent.llm as llm  # noqa: E402
from dlens.agent.llm.types import ProviderError  # noqa: E402
from dlens.agent.tools.provenance import edge_id  # noqa: E402
from dlens.ui import view  # noqa: E402

from ..loop.conftest import call, done, draft, write_shop  # noqa: E402
from ..tools.conftest import make_shop  # noqa: E402

APP = str(Path(view.ROOT / "src/dlens/ui/app.py"))


def _agg_answer():
    agg = next(e for e in make_shop().edges() if e.kind.value == "AGGREGATION")
    return [
        call("trace_upstream", column_id="fct.total"),
        done(),
        draft("total sums stg.amount.", [("fct.total aggregates stg.amount", [edge_id(agg)])]),
    ]


@pytest.fixture
def start(monkeypatch, tmp_path, make_client):
    """``start(script, **query)`` -> a rendered AppTest whose LLM replays ``script``."""
    import streamlit as st

    import dlens.graph as dg

    st.cache_resource.clear()
    root = write_shop(tmp_path / "proj")
    graph = make_shop()
    monkeypatch.setitem(view.PROJECTS, "synthetic_shop", root)
    monkeypatch.setattr(dg, "load_or_build", lambda project, rebuild=False: graph)
    monkeypatch.setenv("DLENS_RUN_DIR", str(tmp_path / "runs"))

    def _start(script, **query):
        client, prov = make_client(script)
        monkeypatch.setattr(llm, "make_client", lambda provider=None: client)
        at = AppTest.from_file(APP, default_timeout=30)
        for k, v in query.items():
            at.query_params[k] = v
        at.run()
        at.provider = prov
        return at

    return _start


def button(at, label):
    return next(b for b in at.button if b.label == label)


def texts(at):
    return [m.value for m in at.markdown]


def ask(at, question="Where does fct.total come from?"):
    at.text_area(key="question").set_value(question).run()
    button(at, "Ask").click().run()
    assert not at.exception, at.exception
    return at


def test_header_stats_and_empty_state(start):
    at = start([])
    assert not at.exception and not at.error
    assert any("3 models · 8 columns · 6 edges" in t for t in texts(at))
    assert any("Local model (Ollama)" in t for t in texts(at))
    assert any("Every claim is checked against the code." in t for t in texts(at))
    assert [t.label for t in at.tabs][:3] == ["Ask", "Explore lineage", "How it works"]


def test_ask_shows_answer_and_chip_opens_source(start):
    at = ask(start(_agg_answer()))
    assert not at.error, [e.value for e in at.error]
    assert any("total sums stg.amount." in t for t in texts(at))
    chips = [b for b in at.button if b.label.startswith("[models/")]
    assert chips, [b.label for b in at.button]
    chips[0].click().run()
    assert not at.exception
    assert at.session_state.detail == "Source"
    assert any("highlighted" in t for t in texts(at))


def test_example_button_asks_immediately(start):
    at = start(_agg_answer())
    empty = [b for b in at.button if b.key and b.key.startswith("empty")]
    assert empty
    empty[0].click().run()
    assert not at.exception
    assert at.session_state.question == empty[0].label
    assert at.session_state.run is not None


def test_ollama_down_shows_the_fix(start):
    down = ProviderError("ollama call failed: Failed to connect to Ollama. Is it running?")
    at = ask(start([down]))
    assert any("not reachable" in e.value for e in at.error)
    assert "ollama serve" in [c.value for c in at.code]
    assert at.session_state.run is None


def test_unknown_project_is_an_error_state(start):
    at = start([], project="nope")
    assert not at.exception
    assert any("Unknown project: nope" in e.value for e in at.error)
