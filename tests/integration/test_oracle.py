"""Perturbation oracle gate (S05, A4; docs/plans/oracle-design.md).

Runs the full oracle on synthetic_shop (about 40 s: dbt seed + compile, then DuckDB in memory) and
checks it against the committed results, the owner's decisions in oracle_exceptions.yml and the
generated report. Same equality pattern as engine_gaps.yml: a new case fails, and a case that goes
away fails until its entry is removed."""

import json
import sys
from pathlib import Path
from typing import Any

import pytest

ROOT = Path(__file__).parents[2]
sys.path.insert(0, str(ROOT / "eval" / "oracle"))

from dlens_oracle.report import (  # noqa: E402
    category_a,
    e2e_ungrouped,
    load_exceptions,
    owner_b,
    render,
    undecided,
)
from dlens_oracle.run import comparable, run_oracle  # noqa: E402

pytestmark = pytest.mark.integration

CORPUS = ROOT / "corpora" / "synthetic_shop"
RESULTS = ROOT / "eval" / "oracle" / "results" / "synthetic_shop.json"


@pytest.fixture(scope="module")
def doc() -> dict[str, Any]:
    fresh = run_oracle(CORPUS, CORPUS / "lineage_spec.yml")
    return json.loads(json.dumps(fresh))


@pytest.fixture(scope="module")
def committed() -> dict[str, Any]:
    return json.loads(RESULTS.read_text())


@pytest.fixture(scope="module")
def exceptions() -> dict[str, Any]:
    return load_exceptions(CORPUS / "oracle_exceptions.yml")


def test_results_equal_committed(doc: dict[str, Any], committed: dict[str, Any]) -> None:
    """Deterministic: re-running gives the committed document (wall time excepted).
    If the corpus or the gold changed on purpose, re-run `make oracle` and commit."""
    assert comparable(doc) == comparable(committed)


def test_errors_equal_committed(doc: dict[str, Any], committed: dict[str, Any]) -> None:
    assert doc["local"]["errors"] == committed["local"]["errors"]
    assert doc["e2e"]["summary"]["errors"] == committed["e2e"]["summary"]["errors"]


def test_controls_and_thresholds(doc: dict[str, Any]) -> None:
    assert doc["controls"]["determinism_failures"] == []
    assert doc["drift"] == {"depends_on": [], "gold_pairs_into_non_children": []}
    assert doc["thresholds"]["uncovered"] == [] and doc["thresholds"]["stale"] == []
    assert [t["id"] for t in doc["thresholds"]["items"] if not t["total_crossings"]] == []


def test_every_category_a_case_is_decided(doc: dict[str, Any], exceptions: dict[str, Any]) -> None:
    assert undecided(doc, exceptions)["category_a"] == []
    recorded = {(e["from"], e["to"], e["check"]) for e in exceptions["category_a"]}
    assert recorded == set(category_a(doc))


def test_untagged_category_b_equals_exceptions(
    doc: dict[str, Any], exceptions: dict[str, Any]
) -> None:
    recorded = {(e["from"], e["to"]) for e in exceptions["category_b"]}
    observed = set(owner_b(doc))
    assert observed - recorded == set(), "new category-B cases: the owner must decide them"
    assert recorded - observed == set(), "stale entries: remove them from oracle_exceptions.yml"
    assert all(e.get("decision") and e.get("reason") for e in exceptions["category_b"])


def test_unexplained_e2e_columns_have_a_likely_reason(
    doc: dict[str, Any], exceptions: dict[str, Any]
) -> None:
    assert e2e_ungrouped(doc, exceptions) == []


def test_report_is_up_to_date(committed: dict[str, Any], exceptions: dict[str, Any]) -> None:
    """ORACLE_REPORT.md is generated from the committed results and the exceptions file."""
    assert (CORPUS / "ORACLE_REPORT.md").read_text() == render(committed, exceptions)
