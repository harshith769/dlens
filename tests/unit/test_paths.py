"""The shared dbt file resolver (S06b): display paths and confined reads."""

from pathlib import Path

import pytest

from dlens.ingest.paths import (
    ProjectFiles,
    display_path,
    manifest_files,
    package_of,
    packages_dir,
    resolve,
)


def _write(path: Path, text: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)
    return path


@pytest.fixture
def linked(tmp_path: Path) -> Path:
    """A project whose package ``pkg`` is a ``dbt deps``-style symlink to a dir outside it.

    outside/            <- the package source (dbt_project.yml name: pkg)
      models/m.sql      <- referenced by the manifest
      secret.txt        <- not referenced
    project/dbt_packages/pkg -> ../../outside
    """
    outside = tmp_path / "outside"
    _write(outside / "dbt_project.yml", "name: pkg\nversion: '1.0'\n")
    _write(outside / "models" / "m.sql", "select 1 as a\n")
    _write(outside / "secret.txt", "do not read\n")
    project = tmp_path / "project"
    _write(project / "dbt_project.yml", "name: root\n")
    _write(project / "models" / "r.sql", "select 2 as b\n")
    (project / "dbt_packages").mkdir()
    (project / "dbt_packages" / "pkg").symlink_to("../../outside")
    return project


ALLOWED = frozenset({"dbt_packages/pkg/models/m.sql"})


def test_display_path_root_vs_package() -> None:
    assert display_path("root", "dbt_packages", "root", "models/a.sql") == "models/a.sql"
    assert display_path("root", "dbt_packages", None, "models/a.sql") == "models/a.sql"
    got = display_path("root", "vendor/pkgs", "jira", "models/a.sql")
    assert got == "vendor/pkgs/jira/models/a.sql"
    assert package_of(got, "vendor/pkgs") == "jira"
    assert package_of("models/a.sql", "dbt_packages") is None


def test_packages_dir_reads_install_path(tmp_path: Path) -> None:
    assert packages_dir(None) == "dbt_packages"
    assert packages_dir(tmp_path) == "dbt_packages"  # no dbt_project.yml
    _write(tmp_path / "dbt_project.yml", "name: x\npackages-install-path: 'vendor/pkgs/'\n")
    assert packages_dir(tmp_path) == "vendor/pkgs"


def test_manifest_files_covers_paths_and_patches() -> None:
    manifest = {
        "nodes": {
            "model.root.a": {
                "package_name": "root",
                "original_file_path": "models/a.sql",
                "patch_path": "root://models/schema.yml",
            },
            "model.pkg.m": {
                "package_name": "pkg",
                "original_file_path": "models/m.sql",
                "patch_path": "pkg://models/pkg.yml",
            },
        },
        "sources": {"source.pkg.s.t": {"package_name": "pkg", "original_file_path": "src.yml"}},
        "docs": {"doc.pkg.d": {"package_name": "pkg", "original_file_path": "docs.md"}},
    }
    assert manifest_files(manifest, "root", "dbt_packages") == {
        "models/a.sql",
        "models/schema.yml",
        "dbt_packages/pkg/models/m.sql",
        "dbt_packages/pkg/models/pkg.yml",
        "dbt_packages/pkg/src.yml",
        "dbt_packages/pkg/docs.md",
    }


def test_root_files_resolve_as_before(linked: Path) -> None:
    assert resolve(linked, "models/r.sql") == (linked / "models" / "r.sql").resolve()
    assert resolve(linked, "../outside/models/m.sql") is None
    assert resolve(linked, "/etc/passwd") is None
    assert resolve(linked, "") is None
    assert resolve(linked, "models/missing.sql") is None


def test_symlinked_package_referenced_file_is_readable(linked: Path) -> None:
    got = resolve(linked, "dbt_packages/pkg/models/m.sql", ALLOWED)
    assert got is not None and got.read_text() == "select 1 as a\n"


def test_symlinked_package_unreferenced_file_is_rejected(linked: Path) -> None:
    assert resolve(linked, "dbt_packages/pkg/secret.txt", ALLOWED) is None
    assert resolve(linked, "dbt_packages/pkg/models/m.sql") is None  # not in the allowlist


def test_symlinked_package_with_wrong_project_name_is_rejected(linked: Path) -> None:
    (linked.parent / "outside" / "dbt_project.yml").write_text("name: other\n")
    assert resolve(linked, "dbt_packages/pkg/models/m.sql", ALLOWED) is None


def test_symlink_to_a_parent_cannot_be_used_to_escape(tmp_path: Path, linked: Path) -> None:
    """``dbt_packages/up -> ..``: even an allowlisted name fails without a matching package."""
    (linked / "dbt_packages" / "up").symlink_to("../..")
    sneaky = "dbt_packages/up/outside/secret.txt"
    assert resolve(linked, sneaky, {sneaky}) is None


def test_project_files_path(linked: Path) -> None:
    files = ProjectFiles(linked, "root", "dbt_packages", ALLOWED)
    assert files.path("root", "models/r.sql") == (
        "models/r.sql",
        (linked / "models" / "r.sql").resolve(),
    )
    shown, _ = files.path("pkg", "models/m.sql") or ("", None)
    assert shown == "dbt_packages/pkg/models/m.sql"
    assert files.path("pkg", "secret.txt") is None
    assert ProjectFiles(None, "root").path("root", "models/r.sql") is None
