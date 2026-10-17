"""Where a dbt node's files are on disk (S06b). Lineage provenance, the chunker and every reader
of a cited file (``safe_read``) use this one resolver.

dbt records ``original_file_path`` (and ``patch_path``) relative to the node's own package. A
root-project file is therefore ``<rel>`` under the project root, and a package file is
``<packages_dir>/<package>/<rel>``. ``packages_dir`` is ``packages-install-path`` from the
project's ``dbt_project.yml``, ``dbt_packages`` by default; dbt-core 1.12 and dbt 2.0 use the same
key and default (2.0 is checked against its docs, not run). That project-relative "display" path
is what the graph stores and what citations name. No absolute path is ever stored.

Reading is confined. A display path must resolve inside the project root, with one exception:
``dbt deps`` installs a ``local:`` package as a symlink, which may point outside the project
(dbt_jira's ``dbt_packages/jira -> ../..``). A path under ``<packages_dir>/<pkg>/`` that leaves the
project root is readable only if

* it is a file the manifest references for package ``<pkg>`` (``allowed``), and
* the package root it resolves to holds a ``dbt_project.yml`` whose ``name`` is ``<pkg>``, and
* it stays inside that package root.

Everything else is rejected, so a symlink such as ``dbt_packages/x -> $HOME`` never widens what
DLens reads (file text can reach a cloud LLM in Ask mode).
"""

from __future__ import annotations

import re
from collections.abc import Collection
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any

DEFAULT_PACKAGES_DIR = "dbt_packages"
_INSTALL_PATH = re.compile(r"^packages-install-path:\s*['\"]?([^'\"\s#]+)", re.MULTILINE)
_NAME = re.compile(r"^name:\s*['\"]?([A-Za-z_][\w]*)", re.MULTILINE)


def packages_dir(project_dir: Path | None) -> str:
    """``packages-install-path`` from ``dbt_project.yml``, else ``dbt_packages``."""
    if project_dir is None:
        return DEFAULT_PACKAGES_DIR
    try:
        text = (project_dir / "dbt_project.yml").read_text(encoding="utf-8")
    except OSError:
        return DEFAULT_PACKAGES_DIR
    m = _INSTALL_PATH.search(text)
    return m.group(1).strip("/") if m else DEFAULT_PACKAGES_DIR


def safe_rel(rel: str) -> bool:
    """A non-empty relative path with no ``..``."""
    p = PurePosixPath(rel)
    return bool(rel) and not p.is_absolute() and ".." not in p.parts


def display_path(root_name: str, packages: str, package: str | None, rel: str) -> str:
    """Project-relative path of a file dbt records relative to ``package``."""
    if not package or package == root_name:
        return rel
    return f"{packages}/{package}/{rel}"


def patch_rel(patch_path: str | None) -> tuple[str | None, str | None]:
    """``pkg://models/schema.yml`` -> (pkg, models/schema.yml)."""
    if not patch_path or "://" not in patch_path:
        return None, None
    pkg, rel = patch_path.split("://", 1)
    return pkg, rel


def manifest_files(manifest: dict[str, Any], root_name: str, packages: str) -> frozenset[str]:
    """Display paths of every file the manifest references (``original_file_path`` and
    ``patch_path`` of nodes, sources, exposures and docs blocks), each under its own package."""
    out: set[str] = set()
    for section in ("nodes", "sources", "exposures", "docs"):
        for entry in (manifest.get(section) or {}).values():
            pkg = entry.get("package_name")
            if entry.get("original_file_path"):
                out.add(display_path(root_name, packages, pkg, entry["original_file_path"]))
            ppkg, prel = patch_rel(entry.get("patch_path"))
            if prel:
                out.add(display_path(root_name, packages, ppkg, prel))
    return frozenset(out)


def package_of(display: str, packages: str) -> str | None:
    """The package a display path is under (``<packages>/<pkg>/...``), or None."""
    parts, prefix = PurePosixPath(display).parts, PurePosixPath(packages).parts
    if len(parts) > len(prefix) + 1 and parts[: len(prefix)] == prefix:
        return parts[len(prefix)]
    return None


def _project_name(root: Path) -> str | None:
    try:
        m = _NAME.search((root / "dbt_project.yml").read_text(encoding="utf-8"))
    except OSError:
        return None
    return m.group(1) if m else None


def resolve(
    project_dir: Path, display: str, allowed: Collection[str] = (), packages: str | None = None
) -> Path | None:
    """The file ``display`` names, or None if it is missing or not readable under the rules in
    the module docstring. ``packages`` defaults to the project's ``packages-install-path``."""
    if not safe_rel(display):
        return None
    base = project_dir.resolve()
    path = (base / display).resolve()
    if not path.is_relative_to(base):
        pkgs = packages if packages is not None else packages_dir(project_dir)
        pkg = package_of(display, pkgs)
        if pkg is None or display not in allowed:
            return None
        pkg_root = (base / pkgs / pkg).resolve()
        if not path.is_relative_to(pkg_root) or _project_name(pkg_root) != pkg:
            return None
    return path if path.is_file() else None


@dataclass(frozen=True)
class ProjectFiles:
    """One dbt project's files: display paths and confined reads."""

    project_dir: Path | None
    root_name: str
    packages: str = DEFAULT_PACKAGES_DIR
    allowed: frozenset[str] = frozenset()
    """Display paths the manifest references (see ``manifest_files``)."""

    @classmethod
    def for_manifest(cls, project_dir: Path | None, manifest: dict[str, Any]) -> ProjectFiles:
        root = (manifest.get("metadata") or {}).get("project_name") or ""
        packages = packages_dir(project_dir)
        return cls(project_dir, root, packages, manifest_files(manifest, root, packages))

    def display(self, package: str | None, rel: str) -> str:
        return display_path(self.root_name, self.packages, package, rel)

    def path(self, package: str | None, rel: str) -> tuple[str, Path] | None:
        """(display path, file) of a file dbt records relative to ``package``, or None."""
        if self.project_dir is None or not safe_rel(rel):
            return None
        shown = self.display(package, rel)
        found = resolve(self.project_dir, shown, self.allowed, self.packages)
        return None if found is None else (shown, found)
