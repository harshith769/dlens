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


def htmls(at):
    return [h.proto.body for h in at.get("html")]


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
    assert any("github.com/harshith769/dlens" in t for t in texts(at))
    assert [t.label for t in at.tabs][:3] == ["Ask", "Explore lineage", "How it works"]


def test_ask_shows_answer_and_chip_opens_source(start):
    at = ask(start(_agg_answer()))
    assert not at.error, [e.value for e in at.error]
    assert any("total sums stg.amount." in t for t in texts(at))
    assert any("Answered" in t and "Verified" in t for t in texts(at))
    assert any("✓" in t and "fct.total aggregates stg.amount" in t for t in texts(at))
    chips = [b for b in at.button if b.label.startswith("[models/")]
    assert chips, [b.label for b in at.button]
    chips[0].click().run()
    assert not at.exception
    assert at.session_state.detail == "Source"
    assert any("highlighted: **line 3**" in t for t in texts(at))
    assert any('class="row hl"' in t and "sum" in t for t in htmls(at))


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


def test_lineage_toggle_draws_cited_then_full_lineage(start):
    at = ask(start(_agg_answer()))
    charts = at.get("graphviz_chart")
    assert charts and "sum(amount)" in charts[0].proto.spec
    at.session_state.lineage_mode = "Full lineage of the column"
    at.run()
    assert not at.exception
    spec = at.get("graphviz_chart")[0].proto.spec
    assert spec.count(" -> ") == 2  # fct.total <- stg.amount <- raw.amt
    assert any("Upstream of fct.total" in c.value for c in at.caption)


def test_steps_and_checks_tabs_render(start):
    at = ask(start(_agg_answer()))
    assert any("dl-timeline" in t and "Tool call" in t and "Validation" in t for t in texts(at))
    frames = at.dataframe
    assert frames and "R2r" in list(frames[0].value["Rule"])


def test_explore_is_instant_and_makes_no_llm_call(start):
    at = start([])
    at.selectbox(key="explore_col").set_value("fct_star.total").run()
    at.slider(key="explore_depth").set_value(10).run()
    assert not at.exception
    assert at.provider.requests == []
    specs = [c.proto.spec for c in at.get("graphviz_chart")]
    assert any(s.count(" -> ") == 3 for s in specs)
    edges = next(f.value for f in at.dataframe if "Where" in f.value.columns)
    assert list(edges["Where"]) == ["models/star.sql:1", "models/fct.sql:3", "models/stg.sql:3"]
    at.selectbox(key="explore_model").set_value("model.p.fct").run()
    assert any("dl-src" in t and "sum" in t for t in htmls(at))
    at.segmented_control(key="explore_dir").set_value("Downstream").run()
    assert any("no downstream lineage" in c.value for c in at.caption)


def test_how_it_works_shows_rules_and_dated_dev_score(start):
    at = start([])
    assert not at.exception
    assert any("**R9**" in t for t in texts(at))
    metric = at.metric[0]
    assert metric.label == "Dev set: 20 hand-written questions (not the benchmark)"
    assert any("eval/reports/dev_r9.json" in c.value for c in at.caption)


def test_history_restores_and_exports_exist(start):
    script = [*_agg_answer(), *_agg_answer()]
    at = ask(start(script))
    assert [b.label for b in at.get("download_button")] == ["Download Markdown", "Download JSON"]
    first = at.session_state.run
    ask(at, "Where does fct.total come from, again?")
    hist = [b for b in at.button if b.key and b.key.startswith("hist")]
    assert len(hist) == 2 and "Where does fct.total come from, again?" in hist[0].label
    assert hist[0].label.startswith(":blue[●]")
    hist[1].click().run()
    assert not at.exception and at.session_state.run is first
    ask(at)  # the first question again: one history entry, now on top
    hist = [b for b in at.button if b.key and b.key.startswith("hist")]
    assert len(hist) == 2 and hist[0].label.endswith("Where does fct.total come from?")


def test_cached_is_a_badge_on_the_answer_not_in_the_header(start):
    at = ask(start(_agg_answer()))
    slot = [t for t in texts(at) if "Local model (Ollama)" in t]
    assert slot and "cached" not in slot[0].lower() and "left today" not in slot[0]
    assert not any(">Cached<" in t for t in texts(at))
    ask(at)  # same question: every LLM call is a cache hit
    assert at.session_state.run.record.tokens.get("cached_calls") == 3
    assert any(">Cached<" in t and "Answered" in t for t in texts(at))
    slot = [t for t in texts(at) if "Local model (Ollama)" in t]
    assert "cached" not in slot[0].lower()
