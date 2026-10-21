"""Scoring regression (S11): the committed S0 records re-score to the committed S0 reports, byte
for byte except the metrics version stamps. Guards ADR 0024's additive fields and the S1 adapter
against moving any existing number.

metrics-design v1.2 (metrics.py 1.3.0) may only ADD: the ``uncovered_part_correct`` and
``interpretation_correct`` rows, the pass-route and spurious-field tables and their per-row
diagnostics. They are stripped before the comparison, so any other change still fails."""

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
_STAMP = re.compile(r"metrics(-design|\.py) \d+\.\d+(\.\d+)?")


V12_METRICS = ("uncovered_part_correct", "interpretation_correct")
V12_DIAG = ("premise_flag", "uncovered_nonempty", "route_premise", "route_uncovered",
            "route_interpretation")  # fmt: skip


def _strip_json(text: str) -> dict:
    d = json.loads(text)
    d.pop("versions")
    for k in ("pass_routes", "spurious_fields"):
        d["summary"].pop(k, None)
    for k in V12_METRICS:
        d["summary"]["metrics"].pop(k, None)
    for r in d["rows"]:
        for k in V12_METRICS:
            r["metrics"].pop(k, None)
        for k in V12_DIAG:
            r["diag"].pop(k, None)
    return d


def _strip_md(text: str) -> str:
    text = _STAMP.sub("", text)
    text = re.sub(r"\n## Pass routes .*?(?=\n## node-set F1)", "", text, flags=re.S)
    return "\n".join(
        line for line in text.splitlines() if not any(f" {k} " in line for k in V12_METRICS)
    )


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
    assert _strip_md(new_md) == _strip_md(committed.with_suffix(".md").read_text())


def test_frozen_s1_report_is_unchanged_but_for_v12_additions(tmp_path: Path) -> None:
    """S1 v2 (frozen records, re-scored only): metrics 1.3.0 adds rows, moves no number."""
    records = ROOT / "eval" / "runs" / "s1" / "s1-qwen3-4b-instruct-2507-q4-k-m-dev.jsonl"
    out = tmp_path / "s1_smoke_dev"
    title = "S1 (vector RAG, local qwen3:4b) on the 96 dev questions"
    argv = ["--records", str(records), "--system", "s1-qwen3-4b", "--out", str(out)]
    assert M.main([*argv, "--title", title]) == 0
    committed = ROOT / "eval" / "reports" / "s1_smoke_dev"
    assert _strip_json(out.with_suffix(".json").read_text()) == _strip_json(
        committed.with_suffix(".json").read_text()
    )
    assert _strip_md(out.with_suffix(".md").read_text()) == _strip_md(
        committed.with_suffix(".md").read_text()
    )
