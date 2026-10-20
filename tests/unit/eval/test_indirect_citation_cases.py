"""Metrics M7 (iv) on the shared indirect-citation cases (tests/fixtures/citations). The validator's
R3 test reads the same cases (tests/unit/agent/validator/test_indirect.py); neither test imports
the other's module, so a drift between the two rules fails one of them."""

import json
from pathlib import Path

import pytest

import metrics as M

FIX = Path(__file__).resolve().parents[2] / "fixtures" / "citations"
SPEC = json.loads((FIX / "indirect_cases.json").read_text())


@pytest.mark.parametrize("case", SPEC["cases"], ids=[c["name"] for c in SPEC["cases"]])
def test_m7_on_the_shared_indirect_cases(case: dict) -> None:
    a, b = case["lines"]
    cite = {"file": SPEC["file"], "line_start": a, "line_end": b, "level": "line"}
    edge = M.EdgeInfo(case["from"], case["to"], case["kind"], case["key"])
    assert M.check_citation("e_x", cite, edge, set(), FIX).valid is case["valid"]
