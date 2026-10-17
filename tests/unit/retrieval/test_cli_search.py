"""`dlens search` (S07): fake-embedder warning, reuse, --kind/--mode, artifacts mode, and the
missing-extra error (runs on the core install too)."""

import shutil
import sys
from pathlib import Path

import pytest
from typer.testing import CliRunner

from dlens.cli import app

from .conftest import EPH_PROJECT

runner = CliRunner()


@pytest.fixture
def target(tmp_path: Path) -> Path:
    shutil.copytree(EPH_PROJECT, tmp_path / "eph_shop")
    t = tmp_path / "eph_shop" / "target"
    assert runner.invoke(app, ["ingest", "--artifacts", str(t)]).exit_code == 0
    return t


def test_missing_extra_exits_2_with_install_hint(
    target: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setitem(sys.modules, "onnxruntime", None)
    r = runner.invoke(app, ["search", "orders", "--artifacts", str(target)])
    assert r.exit_code == 2
    assert "dlens-lineage[retrieval]" in r.output


def test_search_artifacts_fake_warning_and_reuse(
    target: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    pytest.importorskip("bm25s")
    monkeypatch.setenv("DLENS_EMBEDDER", "fake")
    r = runner.invoke(app, ["search", "customer order_seq", "--artifacts", str(target)])
    assert r.exit_code == 0, r.output
    assert "fake embedder: test mode, results are not real" in r.output
    assert "index:  rebuilt: no index yet" in r.output
    assert "customer_orders.order_seq" in r.output
    assert (target / "dlens" / "index" / "meta.json").is_file()
    again = runner.invoke(app, ["search", "customer order_seq", "--artifacts", str(target)])
    assert "fake embedder: test mode" in again.output
    assert "index:  index reused" in again.output
    forced = runner.invoke(app, ["search", "x", "--artifacts", str(target), "--rebuild"])
    assert "rebuilt: --rebuild" in forced.output


def test_kind_and_mode_options(target: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    pytest.importorskip("bm25s")
    monkeypatch.setenv("DLENS_EMBEDDER", "fake")
    r = runner.invoke(
        app, ["search", "orders", "--artifacts", str(target), "--kind", "model", "--mode", "bm25"]
    )
    assert r.exit_code == 0, r.output
    hits = [ln for ln in r.output.splitlines() if ln[:3].strip().rstrip(".").isdigit()]
    assert hits and all("  model  " in ln for ln in hits)
    bad = runner.invoke(app, ["search", "x", "--artifacts", str(target), "--kind", "table"])
    assert bad.exit_code == 2 and "unknown --kind table" in bad.output
    badm = runner.invoke(app, ["search", "x", "--artifacts", str(target), "--mode", "ann"])
    assert badm.exit_code == 2


def test_compiled_basis_is_marked_without_a_project(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    pytest.importorskip("bm25s")
    monkeypatch.setenv("DLENS_EMBEDDER", "fake")
    t = tmp_path / "target"
    shutil.copytree(EPH_PROJECT / "target", t)  # no dbt_project.yml around it
    assert runner.invoke(app, ["ingest", "--artifacts", str(t)]).exit_code == 0
    r = runner.invoke(app, ["search", "order_seq", "--artifacts", str(t), "--kind", "model"])
    assert r.exit_code == 0, r.output
    assert "[compiled]" in r.output and "compiled/eph_shop/" in r.output
