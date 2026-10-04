"""File guards on corpora/synthetic_shop (no dbt): frozen v1 SQL, gold `via` names in the SQL."""

import hashlib
import re
from pathlib import Path

import pytest
import yaml

CORPUS = Path(__file__).parents[2] / "corpora" / "synthetic_shop"
SPEC = CORPUS / "lineage_spec.yml"


def model_sql(model: str) -> str:
    (path,) = CORPUS.glob(f"models/*/{model}.sql")
    return path.read_text()


def test_v1_sql_files_are_frozen() -> None:
    """DESIGN_v2 §1.2 / D2: the 15 v1 SQL files are byte-identical to corpus-v1. The hashes live
    in v1_frozen.sha256 (sha256sum format), so this needs no git tags."""
    lines = (CORPUS / "v1_frozen.sha256").read_text().splitlines()
    assert len(lines) == 15
    for line in lines:
        digest, rel = line.split(maxsplit=1)
        assert hashlib.sha256((CORPUS / rel).read_bytes()).hexdigest() == digest, rel


def _via_rows() -> list[tuple[str, str]]:
    rows = yaml.safe_load(SPEC.read_text())["indirect_edges"]
    return sorted({(r["model"], r["via"]) for r in rows if r.get("via")})


@pytest.mark.parametrize(("model", "via"), _via_rows())
def test_every_via_name_is_a_cte_or_alias_in_the_model_sql(model: str, via: str) -> None:
    """The gold names CTEs and derived tables (docs/explain/gold-spec.md); the SQL must use them.
    `subquery` is the generic label for an unnamed IN-subquery."""
    sql = model_sql(model).lower()
    if via == "subquery":
        assert re.search(r"\bin\s*\(\s*select\b", sql), model
        return
    cte = re.search(rf"(\bwith\s+|,\s*){via}\s+as\s*\(", sql)
    alias = re.search(rf"\)\s+as\s+{via}\b", sql)
    assert cte or alias, f"{model}: no CTE or derived table named {via}"
