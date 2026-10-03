"""Run dbt on a project directory and locate the artifacts DLens needs.

Command choice (tested on jaffle_shop, 3 Oct 2026): ``dbt build --empty`` followed by
``dbt docs generate --no-compile`` gives a catalog identical to a full ``dbt build``
(all 5 models + 3 seeds, same column names, types and order). ``--empty`` makes models
build with zero rows, so ingest is fast and never depends on data volume. Tests are
excluded because they only assert on data and add nothing to lineage. ``docs generate``
is still needed because ``build`` does not write ``catalog.json``.
"""

import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path


class DbtError(RuntimeError):
    """dbt could not be run, or it failed."""


@dataclass(frozen=True)
class DbtArtifacts:
    target_dir: Path

    @property
    def manifest(self) -> Path:
        return self.target_dir / "manifest.json"

    @property
    def catalog(self) -> Path:
        return self.target_dir / "catalog.json"

    @property
    def compiled_dir(self) -> Path:
        return self.target_dir / "compiled"


def find_dbt() -> Path:
    """dbt from the same environment as this interpreter, else the one on PATH."""
    sibling = Path(sys.executable).parent / "dbt"
    if sibling.is_file():
        return sibling
    found = shutil.which("dbt")
    if found:
        return Path(found)
    raise DbtError("dbt executable not found next to the Python interpreter or on PATH.")


def _run(dbt: Path, args: list[str], project_dir: Path) -> None:
    cmd = [str(dbt), *args, "--project-dir", str(project_dir), "--profiles-dir", str(project_dir)]
    result = subprocess.run(cmd, cwd=project_dir, capture_output=True, text=True, check=False)
    if result.returncode != 0:
        tail = "\n".join((result.stdout + result.stderr).strip().splitlines()[-20:])
        raise DbtError(f"`dbt {' '.join(args)}` failed (exit {result.returncode}):\n{tail}")


def run_dbt(project_dir: Path) -> DbtArtifacts:
    """Build the project and return the paths of the generated artifacts."""
    project_dir = project_dir.resolve()
    if not (project_dir / "dbt_project.yml").is_file():
        raise DbtError(f"{project_dir} is not a dbt project (no dbt_project.yml).")
    dbt = find_dbt()
    _run(dbt, ["build", "--empty", "--exclude", "resource_type:test"], project_dir)
    _run(dbt, ["docs", "generate", "--no-compile"], project_dir)
    artifacts = DbtArtifacts(project_dir / "target")
    for path in (artifacts.manifest, artifacts.catalog, artifacts.compiled_dir):
        if not path.exists():
            raise DbtError(f"dbt finished but {path} was not produced.")
    return artifacts
