"""scripts/ask_sheet.py: a blind Ask sheet from fixture records. Codes and order come from the
recorded seed, citation ids are stripped, refusals and clarifications are marked, the key goes to
its own file, a sheet is never overwritten, and a scored sheet reads back as per-answer means."""

import csv
import importlib.util
import sys
from pathlib import Path
from typing import Any

import pytest

SCRIPT = Path(__file__).resolve().parents[3] / "scripts" / "ask_sheet.py"
spec = importlib.util.spec_from_file_location("ask_sheet", SCRIPT)
assert spec is not None and spec.loader is not None
mod = importlib.util.module_from_spec(spec)
sys.modules["ask_sheet"] = mod  # @dataclass looks its module up
spec.loader.exec_module(mod)

QUESTIONS = [
    {
        "id": "dev-77",
        "type": "ask",
        "question": "Which revenue does roas use?",
        "gold": {"facts": [{"fact": "Marketing revenue.", "source": "D.md:1"}, {"fact": "Sum."}]},
    },
    {
        "id": "dev-78",
        "type": "ask",
        "question": "What is aov?",
        "gold": {"facts": [{"fact": "Order value mean.", "source": "D.md:2"}]},
    },
    {"id": "dev-01", "type": "trace", "question": "Upstream of x?", "gold": {}},
]


def rec(question: str, text: str, *, refused: bool = False, ids: str = "e_1a2b3c4d") -> dict:
    return {
        "question": question,
        "final_answer": {
            "answer_text": f"{text} ({ids})",
            "refused": refused,
            "claims": [{"text": f"{text} [{ids}]", "ids": [ids]}, {"text": "It is a sum."}],
        },
    }


S1 = mod.Source("S1", "m1", "runs/s1.jsonl", "s1-m1")
S4 = mod.Source("S4", "m1", "runs/s4.jsonl", "s4-m1")
RUNS: dict[Any, list[dict]] = {
    S1: [
        rec("Which revenue does roas use?", "Marketing revenue", ids="c_9f8e7d6c"),
        rec("What is aov?", "Unknown", refused=True, ids="c_00aa11bb"),
    ],
    S4: [
        rec("Which revenue does roas use?", "Finance revenue"),
        {
            "question": "What is aov?",
            "final_answer": {"clarification": {"candidates": ["model.p.fct_orders.aov"]}},
        },
        rec("Upstream of x?", "not an ask"),
    ],
}


def test_rows_per_fact_and_key_per_answer() -> None:
    rows, key = mod.build(QUESTIONS, RUNS, seed=7)
    assert len(key) == 4 and len({k["code"] for k in key}) == 4
    assert len(rows) == 2 * 2 + 2 * 1  # dev-77 has 2 facts, dev-78 has 1, per system
    assert {r["question_id"] for r in rows} == {"dev-77", "dev-78"}  # only Ask questions
    assert all(r["score"] == "" for r in rows)
    assert [r["question_id"] for r in rows] == sorted(r["question_id"] for r in rows)
    assert {(k["system"], k["question_id"]) for k in key} == {
        ("S1", "dev-77"),
        ("S1", "dev-78"),
        ("S4", "dev-77"),
        ("S4", "dev-78"),
    }


def test_same_seed_same_sheet_other_seed_other_codes() -> None:
    assert mod.build(QUESTIONS, RUNS, seed=7) == mod.build(QUESTIONS, RUNS, seed=7)
    assert {k["code"] for k in mod.build(QUESTIONS, RUNS, seed=7)[1]} != {
        k["code"] for k in mod.build(QUESTIONS, RUNS, seed=8)[1]
    }


def test_answer_text_is_blind_and_marks_refusals_and_clarifications() -> None:
    rows, key = mod.build(QUESTIONS, RUNS, seed=7)
    who = {k["code"]: k["system"] for k in key}
    text = {(who[r["code"]], r["question_id"]): r["answer"] for r in rows}
    assert all("e_" not in t and "c_" not in t and "()" not in t for t in text.values())
    assert text[("S1", "dev-77")] == "Marketing revenue\nIt is a sum."
    assert text[("S1", "dev-78")].startswith("[refused] Unknown")
    assert text[("S4", "dev-78")] == "[clarification requested] candidates: fct_orders.aov"


def test_missing_ask_record_fails() -> None:
    runs = {S1: RUNS[S1][:1]}
    with pytest.raises(ValueError, match="S1 m1: no record for dev-78"):
        mod.build(QUESTIONS, runs)


def test_write_header_key_apart_no_overwrite_and_read_scored(tmp_path: Path) -> None:
    rows, key = mod.build(QUESTIONS, RUNS, seed=7)
    sheet, key_path = tmp_path / "scores" / "ask.csv", tmp_path / "cache" / "key.csv"
    mod.write(rows, key, sheet=sheet, key_path=key_path, seed=7)
    head = sheet.read_text().splitlines()
    assert any("0.5 = the fact is partly stated" in x for x in head[:8])
    assert any("seed 7" in x for x in head[:8])
    assert "system" not in head[len(mod.RULE)]  # the sheet's columns never name the system
    with pytest.raises(FileExistsError):
        mod.write(rows, key, sheet=sheet, key_path=key_path, seed=7)
    with pytest.raises(ValueError, match="score ''"):
        mod.read_scored(sheet, key_path)
    scored = [{**r, "score": "1" if r["fact_no"] == 1 else "0"} for r in rows]
    lines = [x for x in head if x.startswith("#")]
    sheet.write_text("\n".join(lines) + "\n")
    with sheet.open("a", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=mod.FIELDS)
        w.writeheader()
        w.writerows(scored)
    got = mod.read_scored(sheet, key_path)
    assert {k: sorted(v) for k, v in got.items()} == {
        ("S1", "m1"): [0.5, 1.0],
        ("S4", "m1"): [0.5, 1.0],
    }


def test_key_default_path_is_gitignored() -> None:
    root = Path(__file__).resolve().parents[3]
    assert mod.KEY.relative_to(root).parts[:2] == ("eval", "cache")
    assert "eval/cache/" in (root / ".gitignore").read_text().splitlines()
