import json
import re
from pathlib import Path

import pytest
from typer.testing import CliRunner

from dlens import cli
from dlens.agent.answer import WARN_NONE, WARN_PARTIAL
from dlens.agent.tools import Toolbox

from ..tools.conftest import make_shop
from .conftest import call, done, draft

runner = CliRunner()


@pytest.fixture
def wired(monkeypatch, shop_root: Path, make_client, tmp_path: Path):
    """`dlens ask` with the hand-built graph and a scripted provider (no dbt, no Ollama)."""
    box_holder: dict[str, Toolbox] = {}

    def script():
        box = box_holder["box"]
        e = next(i for i in box.emitted_ids if (box.record(i) or {}).get("kind") == "AGGREGATION")
        return draft("total sums stg.amount.", [("fct.total aggregates stg.amount", [e])])

    client, prov = make_client([call("trace_upstream", column_id="fct.total"), done(), script])
    real_toolbox = cli.Toolbox

    def toolbox(graph, project):
        box_holder["box"] = real_toolbox(graph, project)
        return box_holder["box"]

    monkeypatch.setattr(cli, "load_or_build", lambda project, rebuild=False: make_shop())
    monkeypatch.setattr(cli, "make_client", lambda provider=None: client)
    monkeypatch.setattr(cli, "Toolbox", toolbox)
    monkeypatch.setenv("DLENS_RUN_DIR", str(tmp_path / "runs"))
    return shop_root, tmp_path / "runs"


def test_ask_prints_answer_citations_and_trace(wired):
    project, runs = wired
    r = runner.invoke(cli.app, ["ask", "Where does fct.total come from?", "-p", str(project)])
    assert r.exit_code == 0, r.output
    assert "total sums stg.amount." in r.stdout
    assert re.search(r"\[models/\w+\.sql:\d+\]", r.stdout) and "Citations:" in r.stdout
    assert "steps 3 (1 tools, 0 deduped)" in r.stdout and "validator: pass" in r.stdout
    assert len(list(runs.glob("*.jsonl"))) == 1


def test_ask_json(wired):
    project, _ = wired
    r = runner.invoke(
        cli.app, ["ask", "Where does fct.total come from?", "-p", str(project), "--json"]
    )
    assert r.exit_code == 0, r.output
    out = json.loads(r.stdout)
    assert out["answer"]["claims"][0]["edge_ids"]
    assert out["trace"]["llm_calls"] == 3 and out["trace"]["log"].endswith(".jsonl")


def test_ask_unknown_provider_exits_2(monkeypatch, shop_root: Path):
    monkeypatch.setattr(cli, "load_or_build", lambda project, rebuild=False: make_shop())
    r = runner.invoke(cli.app, ["ask", "q", "-p", str(shop_root), "--provider", "nope"])
    assert r.exit_code == 2 and "Unknown" in r.output


def test_validator_label():
    label = cli._validator_label
    assert label(None) == "skipped"
    assert label({"passed": True, "skipped": True}) == "skipped"
    assert label({"passed": True, "repairs": [], "regenerated": False}) == "pass"
    assert label({"passed": True, "repairs": [{}], "regenerated": True}) == (
        "pass, repaired 1, regenerated"
    )
    assert label({"passed": False, "warning": True, "repairs": []}) == "warning"
    assert label({"passed": True, "repairs": [], "completions": [{}, {}]}) == "pass, completed 2"


def _wire_drafts(monkeypatch, shop_root: Path, make_client, tmp_path: Path, claims_of):
    """`dlens ask` whose two answer drafts (first + regenerate) both carry ``claims_of(agg)``."""
    holder: dict[str, Toolbox] = {}

    def script():
        box = holder["box"]
        e = next(i for i in box.emitted_ids if (box.record(i) or {}).get("kind") == "AGGREGATION")
        return draft("fct.total sums stg.amount.", claims_of(e))

    client, _ = make_client([call("trace_upstream", column_id="fct.total"), done(), script, script])
    real_toolbox = cli.Toolbox

    def toolbox(graph, project):
        holder["box"] = real_toolbox(graph, project)
        return holder["box"]

    monkeypatch.setattr(cli, "load_or_build", lambda project, rebuild=False: make_shop())
    monkeypatch.setattr(cli, "make_client", lambda provider=None: client)
    monkeypatch.setattr(cli, "Toolbox", toolbox)
    monkeypatch.setenv("DLENS_RUN_DIR", str(tmp_path / "runs"))


FAKE = ("fct.total is also renamed from raw.amt", ["e_deadbeef"])


def test_ask_shows_the_partial_warning_first(monkeypatch, shop_root, make_client, tmp_path):
    _wire_drafts(
        monkeypatch,
        shop_root,
        make_client,
        tmp_path,
        lambda e: [("fct.total aggregates stg.amount", [e]), FAKE],
    )
    r = runner.invoke(cli.app, ["ask", "Where does fct.total come from?", "-p", str(shop_root)])
    assert r.exit_code == 0, r.output
    assert r.stdout.splitlines()[0] == WARN_PARTIAL
    assert "validator: warning" in r.stdout


def test_ask_shows_the_none_warning_when_refused_by_validator(
    monkeypatch, shop_root, make_client, tmp_path
):
    _wire_drafts(monkeypatch, shop_root, make_client, tmp_path, lambda e: [FAKE])
    r = runner.invoke(cli.app, ["ask", "Where does fct.total come from?", "-p", str(shop_root)])
    assert r.exit_code == 0, r.output
    assert r.stdout.splitlines()[0] == WARN_NONE
    assert "no verifiable claims" in r.stdout
