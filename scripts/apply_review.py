"""Write eval/questions/dev.jsonl from the reviewed candidates (S09, questions-design.md §8).

uv run python scripts/apply_review.py

Runs the review gate first (scripts/check_review.py) and writes nothing unless it passes. Each
question gets its final text (fixes and paraphrase picks applied), a dropped question is replaced
by its spare (which takes the dropped id), and the review decision is recorded in `review`.
Review-only fields (review_flags, spare, stratum) are not written.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from build_review import DECISIONS, merged  # noqa: E402
from check_review import final  # noqa: E402

DEV = ROOT / "eval" / "questions" / "dev.jsonl"
DROP = {"review_flags", "spare", "stratum"}


def main() -> int:
    questions, problems = final(merged(), yaml.safe_load(DECISIONS.read_text()) or {})
    if problems:
        print("refusing: the review is not complete (run make check-review)")
        return 1
    DEV.write_text(
        "".join(
            json.dumps({k: v for k, v in q.items() if k not in DROP}, ensure_ascii=False) + "\n"
            for q in questions
        )
    )
    print(f"wrote {len(questions)} questions to {DEV.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
