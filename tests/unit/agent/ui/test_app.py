"""Smoke test of the Streamlit app with a scripted fake client (no Ollama, no dbt)."""

from pathlib import Path

import pytest

pytest.importorskip("streamlit", reason="needs the ui extra: uv sync --extra ui")
from streamlit.testing.v1 import AppTest  # noqa: E402

import dlens.agent.llm as llm  # noqa: E402
from dlens.agent.tools.provenance import edge_id  # noqa: E402
from dlens.ui import view  # noqa: E402

from ..loop.conftest import call, done, draft, write_shop  # noqa: E402
from ..tools.conftest import make_shop  # noqa: E402

APP = str(Path(view.ROOT / "src/dlens/ui/app.py"))


@pytest.fixture
def app(monkeypatch, tmp_path, make_client):
    import streamlit as st

    st.cache_resource.clear()
    root = write_shop(tmp_path / "proj")
    graph = make_shop()
    agg = next(e for e in graph.edges() if e.kind.value == "AGGREGATION")
    client, _ = make_client(
        [
            call("trace_upstream", column_id="fct.total"),
            done(),
            draft("total sums stg.amount.", [("fct.total aggregates stg.amount", [edge_id(agg)])]),
        ]
    )
    monkeypatch.setitem(view.PROJECTS, "synthetic_shop", root)
    monkeypatch.setattr(llm, "make_client", lambda provider=None: client)
    import dlens.graph as dg

    monkeypatch.setattr(dg, "load_or_build", lambda project, rebuild=False: graph)
    monkeypatch.setenv("DLENS_RUN_DIR", str(tmp_path / "runs"))
    at = AppTest.from_file(APP, default_timeout=30)
    at.run()
    return at


def test_ask_shows_answer_chip_trace_and_source(app):
    assert not app.exception
    assert app.text_input[0].disabled and app.text_input[0].value == "ollama"
    app.text_area(key="question").set_value("Where does fct.total come from?").run()
    app.button[0].click().run()  # Ask
    assert not app.exception and not app.error, [e.value for e in app.error]
    assert any("total sums stg.amount." in m.value for m in app.markdown)
    chips = [b for b in app.button if b.label.startswith("[models/")]
    assert chips, [b.label for b in app.button]
    chips[0].click().run()
    assert not app.exception
    assert any("highlighted" in m.value for m in app.markdown)
    assert any("validator: pass" in m.value for m in app.markdown)
