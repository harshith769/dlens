import json
import re
from pathlib import Path

import pytest
from typer.testing import CliRunner

from dlens import cli
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
        e = sorted(i for i in box.emitted_ids if i.startswith("e_"))[0]
        return draft("total sums stg.amount.", [("total aggregates amount", [e])])

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
    assert "steps 3 (1 tools, 0 deduped)" in r.stdout and "validator: stub" in r.stdout
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
