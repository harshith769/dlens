"""Demo presets: full run records replayed with zero LLM calls, re-validated offline."""

import json
import shutil
from pathlib import Path

import pytest

from dlens.agent.loop import ask
from dlens.agent.tools import Toolbox
from dlens.agent.validator import validate
from dlens.ui import demo, view

from ..loop.conftest import call, done, draft

PROJECT_DIR = demo.projects({})[demo.PROJECT]
REAL = sorted(demo.presets_dir({}).glob("*.json"))


def _graph():
    return demo.load_graph(PROJECT_DIR)


def _scripted_record(make_client, question="Where does stg_payments.amount_usd come from?"):
    """A preset-shaped run on the real bundle, from a scripted provider."""
    from dlens.agent.tools.provenance import edge_id

    graph = _graph()
    edge = next(e for e in graph.edges() if e.to_column.endswith("stg_payments.amount_usd"))
    client, _ = make_client(
        [
            call("trace_upstream", column_id="stg_payments.amount_usd"),
            done(),
            draft("amount_usd renames raw_payments.amt.", [("renamed from amt", [edge_id(edge)])]),
        ]
    )
    client.provider.model = "qwen3:4b-instruct-2507-q4_K_M"
    run = ask(question, client, Toolbox(graph, PROJECT_DIR), project=demo.PROJECT)
    assert run.answer.claims, run.answer
    return run.record


def _check_preset(p: demo.Preset) -> None:
    """Replay rebuilds the same tool payloads, and the final answer passes the validator again."""
    run, box = demo.replay(p, _graph(), PROJECT_DIR)
    recorded = [r for s in p.record.steps for r in s.results if not r.deduped]
    assert [(r.tool, r.args) for r in box.log] == [(r.tool, r.args) for r in recorded]
    for got, want in zip(box.log, recorded, strict=True):
        assert got.llm_payload == want.llm_payload, f"{p.id}: {got.tool} payload changed"
    result = validate(run.answer, box, p.question)
    assert result.passed, (p.id, [f.model_dump() for f in result.failures])
    cited = {i for c in run.answer.claims for i in [*c.edge_ids, *c.chunk_ids]}
    assert cited <= box.emitted_ids


# -- the preset choice ----------------------------------------------------------------------------


def test_preset_ids_passed_in_dev_r9_and_cover_every_kind():
    rows = {r["id"]: r for r in json.loads(view.DEV_REPORT.read_text())["rows"]}
    assert len(demo.PRESET_IDS) == 10 and len(set(demo.PRESET_IDS)) == 10
    assert all(rows[i]["pass"] for i in demo.PRESET_IDS)
    qs = {q["id"]: q for q in map(json.loads, view.DEV_QUESTIONS.read_text().splitlines())}
    chosen = [qs[i] for i in demo.PRESET_IDS]
    subtypes = {q["subtype"] for q in chosen}
    assert {"upstream", "downstream", "reachability", "computed"} <= subtypes
    assert {"ambiguous_chain", "nonexistent_column"} <= subtypes
    assert any(q["expect"].get("yes_no") == "no" for q in chosen)
    assert {q["corpus"] for q in chosen} == {demo.PROJECT}


# -- round trip with a scripted recording ---------------------------------------------------------


def test_preset_file_round_trips_and_revalidates(make_client, tmp_path):
    record = _scripted_record(make_client)
    (tmp_path / "dev-01.json").write_text(demo.preset_json("dev-01", "upstream", record))
    [p] = demo.load_presets(tmp_path)
    assert p.question == record.question and p.badge == "Precomputed with local qwen3:4b"
    _check_preset(p)


def test_replay_makes_no_llm_call_and_matches_the_record(make_client, tmp_path):
    record = _scripted_record(make_client)
    (tmp_path / "dev-01.json").write_text(demo.preset_json("dev-01", "upstream", record))
    [p] = demo.load_presets(tmp_path)
    run, box = demo.replay(p, _graph(), PROJECT_DIR)  # replay takes no client at all
    assert run.record is p.record
    assert run.answer.model_dump(mode="json") == record.final_answer


# -- the recorded presets (once scripts/record_presets.py has run) --------------------------------


@pytest.mark.skipif(not REAL, reason="no recorded presets yet: run scripts/record_presets.py")
def test_all_ten_presets_are_recorded_with_the_local_model():
    loaded = demo.load_presets(demo.presets_dir({}))
    assert [p.id for p in loaded] == list(demo.PRESET_IDS)
    for p in loaded:
        assert p.record.provider == "ollama" and p.record.model.startswith("qwen3:4b")
        assert p.record.project == demo.PROJECT
        # A refusal by code keeps its reason in ``error``; a provider failure must never ship.
        assert not (p.record.error or "").startswith(
            ("ProviderError", "QuotaExceeded", "InputTooLarge")
        )


@pytest.mark.parametrize("path", REAL, ids=[p.stem for p in REAL])
def test_recorded_preset_replays_and_revalidates(path: Path):
    [p] = [x for x in demo.load_presets(path.parent) if x.id == path.stem]
    _check_preset(p)


# -- in the app -----------------------------------------------------------------------------------

pytest.importorskip("streamlit", reason="needs the ui extra: uv sync --extra ui")


@pytest.fixture
def preset_app(monkeypatch, tmp_path, make_client):
    import streamlit as st
    from streamlit.testing.v1 import AppTest

    import dlens.agent.llm as llm

    record = _scripted_record(make_client)
    st.cache_resource.clear()
    copy = tmp_path / "bundle"
    shutil.copytree(demo.ROOT / "demo", copy, ignore=shutil.ignore_patterns("presets"))
    (copy / "presets").mkdir()
    (copy / "presets" / "dev-01.json").write_text(demo.preset_json("dev-01", "upstream", record))
    monkeypatch.setenv("DLENS_DEMO", "1")
    monkeypatch.setenv("DLENS_DEMO_DIR", str(copy))
    monkeypatch.setenv("DLENS_DEMO_STATE_DIR", str(tmp_path / "state"))
    made = []

    def no_client(*a, **k):
        made.append(a)
        raise AssertionError("a preset must not build an LLM client")

    monkeypatch.setattr(llm, "make_client", no_client)
    at = AppTest.from_file(str(demo.ROOT / "src/dlens/ui/app.py"), default_timeout=30)
    at.run()
    return at, made


def test_preset_button_replays_with_zero_llm_calls(preset_app, tmp_path):
    at, made = preset_app
    assert not at.exception
    assert any("Precomputed with local qwen3:4b" in c.value for c in at.caption)
    buttons = [b for b in at.button if b.key == "preset-dev-01"]
    assert buttons
    buttons[0].click().run()
    assert not at.exception, at.exception
    assert made == [] and not at.warning and not at.error
    md = [m.value for m in at.markdown]
    assert any("amount_usd renames raw_payments.amt." in m for m in md)
    assert any("Precomputed with local qwen3:4b" in m and "Answered" in m for m in md)
    assert not any(">Cached<" in m for m in md)
    assert at.session_state.question == "Where does stg_payments.amount_usd come from?"
    assert any("live questions off" in m for m in md)  # presets need no key
    assert (
        demo.calls_left(demo.client_env({"DLENS_DEMO_STATE_DIR": str(tmp_path / "state")}, {}))
        == 50
    )


def test_empty_state_offers_presets(preset_app):
    at, made = preset_app
    empty = [b for b in at.button if b.key and b.key.startswith("empty-")]
    assert [b.key for b in empty] == ["empty-dev-01"]
    empty[0].click().run()
    assert not at.exception and made == []
    assert at.session_state.run is not None and at.session_state.preset
