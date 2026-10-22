"""scripts/pilot_table.py: per-question values come from metrics.py rows, S1-vs-S4 uses
metrics.py's paired bootstrap and McNemar, losses list every question where S4 < S1, and the
rendered panel carries the banner, the temperature note and every row."""

import importlib.util
import json
import sys
from pathlib import Path
from typing import Any

import metrics as M

ROOT = Path(__file__).resolve().parents[3]
SCRIPT = ROOT / "scripts" / "pilot_table.py"
spec = importlib.util.spec_from_file_location("pilot_table", SCRIPT)
assert spec is not None and spec.loader is not None
mod = importlib.util.module_from_spec(spec)
sys.modules["pilot_table"] = mod  # @dataclass looks its module up
spec.loader.exec_module(mod)


def row(qid: str, composite: str | None, subtype: str = "upstream", **metrics: float) -> dict:
    return {
        "id": qid,
        "composite": composite,
        "subtype": subtype,
        "kind": "answered",
        "metrics": metrics,
    }


def result(*rows: dict) -> dict[str, Any]:
    return {"rows": list(rows)}


S1 = result(
    row("dev-01", "trace", headline_f1=0.5, fully_correct=0.0),
    row("dev-02", "impact", "downstream", headline_f1=1.0, fully_correct=1.0),
    row("dev-10", None, "yesno", yesno_correct=1.0, fully_correct=1.0),
)
S4 = result(
    row("dev-01", "trace", headline_f1=1.0, fully_correct=1.0),
    row("dev-02", "impact", "downstream", headline_f1=0.5, fully_correct=0.0),
    row("dev-10", None, "yesno", yesno_correct=0.0, fully_correct=0.0),
)


def test_per_question_node_f1_is_the_composite_headline() -> None:
    assert mod.per_question(S1, "node_f1") == {"dev-01": 0.5, "dev-02": 1.0}
    assert mod.per_question(S1, "yesno_correct") == {"dev-10": 1.0}


def test_compare_uses_metrics_paired_bootstrap_and_mcnemar() -> None:
    c = mod.compare(S1, S4)
    assert c["paired"] == M.paired_bootstrap(
        {"dev-01": 0.5, "dev-02": 1.0}, {"dev-01": 1.0, "dev-02": 0.5}
    )
    assert c["paired"]["diff"] == 0.0 and c["n_binary"] == 3
    assert (c["mcnemar"]["b"], c["mcnemar"]["c"]) == (
        2,
        1,
    )  # S1 only: dev-02, dev-10; S4 only: dev-01


def test_losses_lists_f1_for_composites_and_fully_correct_otherwise() -> None:
    assert [(x["id"], x["metric"]) for x in mod.losses(S1, S4)] == [
        ("dev-02", "node_f1"),
        ("dev-10", "fully_correct"),
    ]
    assert mod.losses(S4, S4) == []


def test_render_qwen_panel_from_committed_records(tmp_path: Path) -> None:
    """The panel table from real committed records (S1 v2 stands in for the pilot S1 run)."""
    rows = mod._panel(
        "eval/runs/s1/s1-qwen3-4b-instruct-2507-q4-k-m-dev.jsonl",
        "eval/runs/s4/s4-qwen3-4b-instruct-2507-q4-k-m-dev.jsonl",
        "qwen3-4b",
    )
    results = {r.label: mod.score(r, tmp_path) for r in rows}
    md = mod.render("qwen", "qwen3:4b", rows, results)
    assert "**pilot (dev), qwen.**" in md and "temperature 0" in md and "1.0" in md
    for r in rows:
        assert f"| {r.label} |" in md
    assert "S4 validated vs S1" in md and "S4 raw vs S1" in md
    validated = json.loads((tmp_path / "s4_validated.json").read_text())
    assert validated["summary"]["metrics"]["node_f1"]["n"] == 68
    assert (
        f"Losses: S4 validated below S1 ({len(mod.losses(results['S1'], validated))} questions)"
        in md
    )
    assert str(Path.home()) not in md


def test_render_combined_side_by_side_and_ask_pending(tmp_path: Path) -> None:
    """The final layout from committed qwen records standing in for both panels (no Gemini run
    is read): one column per panel, S1 vs S4 per panel, Ask pending until the sheet is scored."""
    rows = mod.PANELS["qwen"]["rows"]
    results = {r.label: mod.score(r, tmp_path) for r in rows}
    panels = {"qwen": ("qwen title", rows, results), "gemini": ("gemini title", rows, results)}
    ask = mod.ask_table(tmp_path / "none.csv", tmp_path / "none_key.csv")
    md = mod.render_combined(panels, ask)
    assert "node-set F1 (qwen) | node-set F1 (gemini)" in md and "temperature 0" in md
    assert "| qwen | S4 validated vs S1 |" in md and "| gemini | S4 raw vs S1 |" in md
    assert "Pending: the blind sheet is not scored yet" in md
    assert "## Panel qwen: qwen title" in md and "### Losses: S4 validated below S1" in md
    assert str(Path.home()) not in md


def test_ask_table_reads_the_scored_sheet(tmp_path: Path) -> None:
    sheet, key = tmp_path / "ask.csv", tmp_path / "key.csv"
    sheet.write_text(
        "# rule\ncode,question_id,question,fact_no,fact,fact_source,answer,score,note\n"
        "AX,dev-77,q,1,f,s,a,1,\nAX,dev-77,q,2,f,s,a,0,\nAY,dev-77,q,1,f,s,a,0.5,\n"
    )
    key.write_text(
        "# key\ncode,system,model,view,records,question_id\n"
        "AX,S4,m,validated,r,dev-77\nAY,S1,m,validated,r,dev-77\n"
    )
    lines = mod.ask_table(sheet, key)
    assert "| S1 | m | 0.500 (1) |" in lines and "| S4 | m | 0.500 (1) |" in lines


def test_fresh_llm_latency_keeps_only_questions_with_all_calls_fresh(tmp_path: Path) -> None:
    recs = [
        {"tokens": {"llm_calls": 3, "cached_calls": 0}, "timings": {"total_ms": 9000.0}},
        {"tokens": {"llm_calls": 3, "cached_calls": 1}, "timings": {"total_ms": 1.0}},  # partial
        {"tokens": {"llm_calls": 0, "cached_calls": 0}, "timings": {"total_ms": 2.0}},  # code
        {"tokens": {"llm_calls": 4, "cached_calls": 0}, "timings": {"total_ms": 5000.0}},
    ]
    p = tmp_path / "r.jsonl"
    p.write_text("\n".join(json.dumps(r) for r in recs) + "\n")
    f = mod.fresh_llm_latency(p)
    assert f == {"n": 2, "p50": M.percentile([9000.0, 5000.0], 50), "p95": 9000.0}
    assert mod._fresh_cell(f).endswith("(n = 2, small n)")


def test_ask_pending_counts_csv_rows_not_lines_and_notes_are_included(tmp_path: Path) -> None:
    sheet = tmp_path / "ask.csv"
    sheet.write_text(
        "# rule\ncode,question_id,question,fact_no,fact,fact_source,answer,score,note\n"
        'AX,dev-77,q,1,f,s,"two\nlines",,\nAY,dev-77,q,1,f,s,a,,\n'
    )
    (line,) = mod.ask_table(sheet, tmp_path / "no_key.csv")
    assert "Pending owner scoring (M11)" in line and "2 rows" in line
    rows = mod.PANELS["qwen"]["rows"]
    results = {r.label: mod.score(r, tmp_path) for r in rows}
    md = mod.render_combined({"qwen": ("t", rows, results)}, [line], "## Run notes\n\nx\n")
    assert md.index("## Ask") < md.index("## Run notes") < md.index("## Panel qwen")
