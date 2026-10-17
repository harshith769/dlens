"""Artifact graph cache (ADR 0013): <target>/dlens/ by default, reused while the manifest,
catalog, dialect and dlens version are unchanged; nothing is written anywhere else."""

import json
import shutil
from pathlib import Path

import pytest

from dlens.graph import load_or_build_artifacts

EPH = Path(__file__).parents[1] / "fixtures" / "artifacts" / "eph_shop"


@pytest.fixture
def project(tmp_path: Path) -> Path:
    dest = tmp_path / "eph_shop"
    shutil.copytree(EPH, dest)
    return dest


def _tree(root: Path) -> set[str]:
    return {p.relative_to(root).as_posix() for p in root.rglob("*")}


def test_writes_only_under_target_dlens(project: Path) -> None:
    before = _tree(project.parent)
    built = load_or_build_artifacts(project / "target")
    assert not built.reused
    assert built.cache_dir == project / "target" / "dlens"
    added = _tree(project.parent) - before
    assert added == {
        "eph_shop/target/dlens",
        "eph_shop/target/dlens/graph.json",
        "eph_shop/target/dlens/meta.json",
    }
    meta = json.loads((built.cache_dir / "meta.json").read_text())
    assert meta["dialect"] == "duckdb" and meta["catalog_sha256"] and meta["manifest_sha256"]


def test_reused_when_unchanged_and_rebuilt_after_manifest_change(project: Path) -> None:
    target = project / "target"
    first = load_or_build_artifacts(target)
    again = load_or_build_artifacts(target)
    assert again.reused and again.graph.columns() == first.graph.columns()
    manifest = target / "manifest.json"
    manifest.write_text(manifest.read_text() + "\n")  # any byte change: new hash
    assert not load_or_build_artifacts(target).reused
    assert load_or_build_artifacts(target).reused
    assert not load_or_build_artifacts(target, rebuild=True).reused


def test_catalog_removal_and_dialect_change_rebuild(project: Path) -> None:
    target = project / "target"
    load_or_build_artifacts(target)
    built = load_or_build_artifacts(target, dialect="postgres")
    assert not built.reused and built.info.dialect == "postgres"
    (target / "catalog.json").unlink()
    built = load_or_build_artifacts(target, dialect="postgres")
    assert not built.reused and built.info.catalog_less


def test_out_overrides_cache_dir(project: Path, tmp_path: Path) -> None:
    out = tmp_path / "elsewhere"
    before = _tree(project)
    built = load_or_build_artifacts(project / "target", out=out)
    assert built.cache_dir == out and (out / "graph.json").is_file()
    assert _tree(project) == before  # the user's project is untouched
    assert load_or_build_artifacts(project / "target", out=out).reused


def test_corrupt_cache_is_rebuilt(project: Path) -> None:
    target = project / "target"
    built = load_or_build_artifacts(target)
    (built.cache_dir / "graph.json").write_text("{not json")
    assert not load_or_build_artifacts(target).reused
