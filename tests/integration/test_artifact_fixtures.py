"""The committed artifact fixtures still match a fresh dbt build (scripts/make_artifact_fixture.py).

If this fails after a corpus or dbt change, regenerate: the script's docstring has the commands.
"""

import importlib.util
import json
from pathlib import Path

import pytest

pytestmark = pytest.mark.integration

ROOT = Path(__file__).parents[2]
_spec = importlib.util.spec_from_file_location(
    "make_artifact_fixture", ROOT / "scripts" / "make_artifact_fixture.py"
)
assert _spec and _spec.loader
maf = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(maf)


def _committed(name: str) -> dict[str, object]:
    out = maf.output_dir(name)
    files: dict[str, object] = {}
    for path in sorted(p for p in out.rglob("*") if p.is_file()):
        rel = path.relative_to(out).as_posix()
        text = path.read_text(encoding="utf-8")
        files[rel] = json.loads(text) if rel.endswith(".json") else text
    return files


@pytest.mark.parametrize("name", ["eph_shop", "synthetic_shop"])
def test_fixture_matches_fresh_build(name: str) -> None:
    fresh = json.loads(json.dumps(maf.volatile_free(maf.build(name))))
    assert fresh == _committed(name)
