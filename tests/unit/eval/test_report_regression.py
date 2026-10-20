"""Scoring regression (S11): the committed S0 records re-score to the committed S0 reports, byte
for byte except the metrics version stamps. Guards ADR 0024's additive fields and the S1 adapter
against moving any existing number."""

import json
import re
from pathlib import Path

import pytest

import metrics as M

ROOT = Path(__file__).resolve().parents[3]

TITLES = {
    "gold": "S0-gold on the 96 dev questions",
    "linked": "S0-linked (hybrid off) on the 96 dev questions",
}
_STAMP = re.compile(r"metrics\.py \d+\.\d+\.\d+")


def _strip_json(text: str) -> dict:
    d = json.loads(text)
    d.pop("versions")
    return d


@pytest.mark.parametrize("variant", ["gold", "linked"])
def test_s0_reports_are_unchanged(variant: str, tmp_path: Path) -> None:
    records = ROOT / "eval" / "runs" / "s0" / f"s0-{variant}-dev.jsonl"
    out = tmp_path / f"s0_{variant}_dev"
    argv = ["--records", str(records), "--system", f"s0-{variant}", "--out", str(out)]
    assert M.main([*argv, "--title", TITLES[variant]]) == 0
    committed = ROOT / "eval" / "reports" / f"s0_{variant}_dev"
    new_json = out.with_suffix(".json").read_text()
    assert _strip_json(new_json) == _strip_json(committed.with_suffix(".json").read_text())
    new_md = out.with_suffix(".md").read_text()
    assert _STAMP.sub("", new_md) == _STAMP.sub("", committed.with_suffix(".md").read_text())
