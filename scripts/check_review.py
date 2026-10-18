"""Gate for the owner's dev question review (S09, questions-design.md §8).

uv run python scripts/check_review.py     # or: make check-review

Fails (exit 1) unless:
- every question has a decision of accept, fix (with non-empty `text`) or drop (with a
  `replacement` spare);
- a replacement is a spare of the same row, decided accept or fix, and used once; unused spares
  stay `unused`;
- a fixed identifier-worded question still names its target id (or the entry re-labels `wording`);
- the final 96 match the count table (questions-design.md §1) by row, and by wording unless the
  file sets `allow_wording_shift: true`.
Nothing counts until this passes; scripts/apply_review.py runs it first.
"""

from __future__ import annotations

import sys
from collections import Counter
from pathlib import Path
from typing import Any

import yaml

ROOT = Path(__file__).parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from build_review import DECISIONS, merged  # noqa: E402

ROWS = {
    "trace 1": 8, "trace 2-3": 11, "trace 4-5": 11, "trace 6+": 11, "false_premise": 4,
    "impact": 24, "yesno": 6, "ask": 12, "unanswerable": 9,
}  # fmt: skip
WORDING = {"identifier": 48, "name_words": 18, "description": 10, "paraphrase": 20}
DONE = {"accept", "fix"}


def row(q: dict[str, Any]) -> str:
    if q["subtype"] == "false_premise":
        return "false_premise"
    if q["type"] == "trace":
        return f"trace {q['hop_bucket']}"
    if q["subtype"] == "yesno":
        return "yesno"
    return str(q["type"])


def final(
    questions: list[dict[str, Any]], doc: dict[str, Any]
) -> tuple[list[dict[str, Any]], list[str]]:
    """The reviewed 96 (fixes applied, drops replaced) and the list of problems."""
    dec: dict[str, Any] = doc.get("decisions") or {}
    by_id = {q["id"]: q for q in questions}
    problems: list[str] = []
    out: list[dict[str, Any]] = []
    used: dict[str, str] = {}

    def apply(q: dict[str, Any], entry: dict[str, Any], new_id: str) -> dict[str, Any]:
        r = {**q, "id": new_id}
        if entry.get("wording"):
            r["wording"] = entry["wording"]
        if entry["decision"] == "fix":
            r["question"] = entry["text"]
            ident = r["wording"] == "identifier" and r["type"] != "unanswerable"
            if ident and r["target"] not in entry["text"]:
                problems.append(f"{new_id}: fixed identifier question must name {r['target']}")
        r["review"] = {k: entry[k] for k in ("decision", "note") if entry.get(k)}
        if q["id"] != new_id:
            r["review"]["replaced_by_spare"] = q["id"]
        return r

    for q in questions:
        if q.get("spare"):
            continue
        entry = dec.get(q["id"]) or {}
        d = entry.get("decision")
        if d == "pending" or d is None:
            problems.append(f"{q['id']}: decision pending")
        elif d == "fix" and not str(entry.get("text") or "").strip():
            problems.append(f"{q['id']}: fix needs text")
        elif d == "drop":
            rep = entry.get("replacement")
            spare = by_id.get(rep) if rep else None
            if not spare or not spare.get("spare"):
                problems.append(f"{q['id']}: drop needs a spare as replacement")
            elif row(spare) != row(q):
                problems.append(f"{q['id']}: replacement {rep} is row {row(spare)}, not {row(q)}")
            elif rep in used:
                problems.append(f"{rep}: replaces both {used[rep]} and {q['id']}")
            elif (dec.get(rep) or {}).get("decision") not in DONE:
                problems.append(f"{rep}: a replacement must be decided accept or fix")
            else:
                used[rep] = q["id"]
                out.append(apply(spare, dec[rep], q["id"]))
        elif d in DONE:
            out.append(apply(q, entry, q["id"]))
        else:
            problems.append(f"{q['id']}: unknown decision {d!r}")
    for q in questions:
        if q.get("spare") and q["id"] not in used:
            d = (dec.get(q["id"]) or {}).get("decision", "unused")
            if d != "unused":
                problems.append(f"{q['id']}: decided {d} but replaces nothing (set unused)")
    if not problems:
        rows = Counter(row(q) for q in out)
        problems += [f"row {r}: {rows[r]} questions, table says {n}" for r, n in ROWS.items()
                     if rows[r] != n]  # fmt: skip
        words = Counter(q["wording"] for q in out)
        if words != Counter(WORDING) and not doc.get("allow_wording_shift"):
            problems.append(f"wording mix {dict(words)} != {WORDING} (re-label, or set "
                            "allow_wording_shift: true)")  # fmt: skip
    return sorted(out, key=lambda q: q["id"]), problems


def main() -> int:
    doc = yaml.safe_load(DECISIONS.read_text()) or {}
    _, problems = final(merged(), doc)
    if problems:
        pending = sum("pending" in p for p in problems)
        print(f"review NOT complete: {len(problems)} problem(s), {pending} pending")
        for p in problems[:40]:
            print("  " + p)
        return 1
    print("review complete: every decision set; counts match the table")
    return 0


if __name__ == "__main__":
    sys.exit(main())
