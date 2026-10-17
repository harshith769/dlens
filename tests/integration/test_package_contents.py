"""The wheel and sdist ship the dlens package only: no demo bundle and no corpora, in
particular not the vendored set-E project corpora/dbt_jira (S06)."""

import subprocess
import tarfile
import zipfile
from pathlib import Path

import pytest

pytestmark = pytest.mark.integration

ROOT = Path(__file__).parents[2]


def test_wheel_and_sdist_exclude_demo_and_corpora(tmp_path: Path) -> None:
    subprocess.run(
        ["uv", "build", "--out-dir", str(tmp_path)], cwd=ROOT, check=True, capture_output=True
    )
    [wheel] = tmp_path.glob("*.whl")
    [sdist] = tmp_path.glob("*.tar.gz")
    names = zipfile.ZipFile(wheel).namelist() + tarfile.open(sdist).getnames()
    assert any(n.endswith("dlens/cli.py") for n in names)
    bad = [
        n
        for n in names
        if "corpora/" in n or "dbt_jira" in n or "/demo/" in n or n.startswith("demo/")
    ]
    assert bad == []
