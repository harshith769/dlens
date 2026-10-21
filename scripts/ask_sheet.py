"""S13 blind Ask sheet (metrics-design M11; docs/plans/pilot-design.md). Every system's answer to
the 12 Ask questions goes under a random code, one row per (answer, gold fact), with an empty
0 / 0.5 / 1 score column. The key (code -> system, model, view) is written to a separate,
gitignored file that the owner opens only after scoring. Claude Code never scores Ask.

    uv run python scripts/ask_sheet.py          # -> eval/scores/ask_pilot.csv
                                                #    eval/cache/s13-ask-key/ask_pilot_key.csv

Blinding: codes and row order come from ``random.Random(seed)`` (the seed is written in the
sheet header and the key). Citation ids (``e_…`` edges, ``c_…`` chunks) are stripped from the
answer text, because their prefix names the system. Wording can still hint at a system; that
limit is stated in the header.

The view is ``validated`` for every system: the answer the system ships (S1 has no other view).
The sheet is never overwritten (a scored sheet is the owner's data); pass ``--out`` elsewhere.
"""

from __future__ import annotations

import argparse
import csv
import json
import random
import re
import sys
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "eval"))

import metrics as M  # noqa: E402

SEED = 20261021  # recorded in the sheet header and the key
SHEET = ROOT / "eval" / "scores" / "ask_pilot.csv"
KEY = ROOT / "eval" / "cache" / "s13-ask-key" / "ask_pilot_key.csv"  # gitignored (eval/cache/)
VIEW = "validated"
RULE = [
    "Blind Ask sheet (metrics-design M11). Score each row: one gold fact against one answer.",
    "1 = the fact is stated correctly.",
    "0.5 = the fact is partly stated, or stated with an error.",
    "0 = the fact is absent or wrong (a refusal or a clarification scores 0 on every fact).",
    "Answer score = mean over its facts; system score = mean over its answers (n = 12).",
    "Codes are random (seed {seed}); citation ids are stripped. Wording may still hint at a "
    "system: score the content only.",
    "Do not open the key file until every score cell is filled.",
]
FIELDS = [
    "code",
    "question_id",
    "question",
    "fact_no",
    "fact",
    "fact_source",
    "answer",
    "score",
    "note",
]
KEY_FIELDS = ["code", "system", "model", "view", "records"]
_IDS = re.compile(r"\b[ec]_[0-9a-f]{4,}\b")


@dataclass(frozen=True)
class Source:
    system: str  # S1 | S4
    model: str
    records: str  # repo-relative
    metrics_system: str  # metrics.py --system (picks the adapter)


SOURCES = [
    Source(
        "S1",
        "qwen3:4b",
        "eval/runs/s1/pilot/s1-qwen3-4b-instruct-2507-q4-k-m-dev.jsonl",
        "s1-qwen3-4b",
    ),
    Source(
        "S4",
        "qwen3:4b",
        "eval/runs/s4/s4-qwen3-4b-instruct-2507-q4-k-m-dev.jsonl",
        "s4-qwen3-4b",
    ),
    Source(
        "S1",
        "gemini-3.5-flash-lite",
        "eval/runs/s1/pilot/s1-gemini-3-5-flash-lite-dev.jsonl",
        "s1-gemini-3-5-flash-lite",
    ),
    Source(
        "S4",
        "gemini-3.5-flash-lite",
        "eval/runs/s4/s4-gemini-3-5-flash-lite-dev.jsonl",
        "s4-gemini-3-5-flash-lite",
    ),
]


def ask_questions(questions: Sequence[Mapping[str, Any]]) -> list[Mapping[str, Any]]:
    return [q for q in questions if q.get("type") == "ask"]


def answer_text(pred: M.Prediction) -> str:
    """What the owner reads: the answer text, then each claim not already in it, ids stripped.
    Refusals and clarifications are marked, so they score 0 by the header rule."""
    if pred.kind == "clarification":
        return "[clarification requested] candidates: " + ", ".join(pred.clarification)
    if pred.kind in ("missing", "crashed"):
        return f"[{pred.kind}: no answer]"
    lead = _blind(pred.answer_text)
    parts = [lead] if lead else []
    for c in pred.claims:
        t = _blind(c.get("text", ""))
        if t and t not in parts and t not in lead:
            parts.append(t)
    text = "\n".join(parts) or "(empty answer)"
    return "[refused] " + text if pred.kind == "refused" else text


def _blind(text: str) -> str:
    """Citation ids removed (their prefix names the system), with the brackets left empty."""
    text = re.sub(r"\(\s*[,;\s]*\)|\[\s*[,;\s]*\]", "", _IDS.sub("", text))
    return re.sub(r"[ \t]+([.,;:])", r"\1", re.sub(r"[ \t]{2,}", " ", text)).strip()


def build(
    questions: Sequence[Mapping[str, Any]],
    runs: Mapping[Source, Sequence[Mapping[str, Any]]],
    seed: int = SEED,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """``(sheet rows, key rows)``. Every source must answer every Ask question (no partial run
    goes on the sheet)."""
    asks = ask_questions(questions)
    rng = random.Random(seed)
    answers: list[tuple[str, Mapping[str, Any], str]] = []
    key: list[dict[str, Any]] = []
    used: set[str] = set()
    for src, records in runs.items():
        by_text = {q["question"]: q["id"] for q in asks}
        by_id = {by_text[r["question"]]: r for r in records if r.get("question") in by_text}
        missing = [q["id"] for q in asks if q["id"] not in by_id]
        if missing:
            raise ValueError(f"{src.system} {src.model}: no record for {', '.join(missing)}")
        adapter = M.adapter_for(src.metrics_system)
        for q in asks:
            code = _code(rng, used)
            text = answer_text(adapter(by_id[q["id"]], VIEW))
            answers.append((code, q, text))
            key.append(
                {
                    "code": code,
                    "system": src.system,
                    "model": src.model,
                    "view": VIEW,
                    "records": src.records,
                    "question_id": q["id"],
                }
            )
    rng.shuffle(answers)
    answers.sort(key=lambda a: a[1]["id"])  # grouped by question; random order within it
    rows = []
    for code, q, text in answers:
        for i, f in enumerate(q["gold"]["facts"], 1):
            rows.append(
                {
                    "code": code,
                    "question_id": q["id"],
                    "question": q["question"],
                    "fact_no": i,
                    "fact": f["fact"],
                    "fact_source": f.get("source", ""),
                    "answer": text,
                    "score": "",
                    "note": "",
                }
            )
    key.sort(key=lambda k: k["code"])
    return rows, key


def _code(rng: random.Random, used: set[str]) -> str:
    while True:
        code = "A" + "".join(rng.choice("BCDFGHJKLMNPQRSTVWXZ23456789") for _ in range(4))
        if code not in used:
            used.add(code)
            return code


def write(
    rows: Sequence[Mapping[str, Any]],
    key: Sequence[Mapping[str, Any]],
    *,
    sheet: Path,
    key_path: Path,
    seed: int,
) -> None:
    if sheet.exists():
        raise FileExistsError(f"{sheet.name} exists (it may hold scores); not overwritten")
    sheet.parent.mkdir(parents=True, exist_ok=True)
    with sheet.open("w", newline="") as fh:
        for line in RULE:
            fh.write("# " + line.format(seed=seed) + "\n")
        w = csv.DictWriter(fh, fieldnames=FIELDS)
        w.writeheader()
        w.writerows(rows)
    key_path.parent.mkdir(parents=True, exist_ok=True)
    with key_path.open("w", newline="") as fh:
        fh.write(f"# Ask sheet key, seed {seed}. Open only after the sheet is scored.\n")
        w = csv.DictWriter(fh, fieldnames=[*KEY_FIELDS, "question_id"])
        w.writeheader()
        w.writerows(key)


def read_scored(sheet: Path, key_path: Path) -> dict[tuple[str, str], list[float]]:
    """``{(system, model): [answer score, …]}`` from a scored sheet and its key (answer score =
    mean over its facts, M11). Fails if any score cell is empty or not 0 / 0.5 / 1."""

    def rows(p: Path) -> list[dict[str, str]]:
        lines = [x for x in p.read_text().splitlines() if not x.startswith("#")]
        return list(csv.DictReader(lines))

    who = {k["code"]: (k["system"], k["model"]) for k in rows(key_path)}
    per: dict[str, list[float]] = {}
    for r in rows(sheet):
        s = r["score"].strip()
        if s not in ("0", "0.5", "1", "1.0", "0.0"):
            raise ValueError(f"{r['code']} {r['question_id']} fact {r['fact_no']}: score {s!r}")
        per.setdefault(r["code"], []).append(float(s))
    out: dict[tuple[str, str], list[float]] = {}
    for code, facts in sorted(per.items()):
        out.setdefault(who[code], []).append(sum(facts) / len(facts))
    return out


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawTextHelpFormatter)
    ap.add_argument("--seed", type=int, default=SEED)
    ap.add_argument("--out", type=Path, default=SHEET)
    ap.add_argument("--key", type=Path, default=KEY)
    ns = ap.parse_args(argv)
    questions = M.load_questions(ROOT / "eval/questions/dev.jsonl").items
    missing = [s.records for s in SOURCES if not (ROOT / s.records).exists()]
    if missing:
        print(f"ask_sheet: missing records {missing}", file=sys.stderr)
        return 2
    runs = {
        s: [json.loads(x) for x in (ROOT / s.records).read_text().splitlines() if x.strip()]
        for s in SOURCES
    }
    rows, key = build(questions, runs, ns.seed)
    write(rows, key, sheet=ns.out, key_path=ns.key, seed=ns.seed)
    print(
        f"ask_sheet: {len(rows)} rows, {len(key)} answers -> {ns.out.name}; key {ns.key.name}",
        file=sys.stderr,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
