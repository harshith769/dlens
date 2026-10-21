"""S4 reproducibility check (S12b, owner decision at STOP 2).

Compares the uncached full S4 dev run with a second pass from the same cache. The second pass
must make **0 uncached calls** (every LLM step cached, every record ``cache: hit``), and the
records must be equal except for the fields that differ between any two passes by construction:
``EXCLUDED`` (ids and clocks, and the cache flags themselves).

This proves the records are reproducible from the cache. It does not show that the model is
deterministic: a second uncached run may answer differently.

    uv run python scripts/check_s4_repro.py --first eval/runs/s4/<file>.jsonl \\
        --second eval/cache/s4-s12b-repro-out/<file>.jsonl
"""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

# (path, …) of each field allowed to differ; "steps[]" applies to every step
EXCLUDED = (
    ("run_id",),
    ("started_at",),
    ("timings",),
    ("steps[]", "latency_ms"),
    ("steps[]", "cached"),
    ("cache",),
    ("tokens", "cached_calls"),
)


def without_excluded(record: Mapping[str, Any]) -> dict[str, Any]:
    out = json.loads(json.dumps(record))
    for path in EXCLUDED:
        if path[0] == "steps[]":
            for step in out.get("steps") or []:
                step.pop(path[1], None)
        elif len(path) == 1:
            out.pop(path[0], None)
        elif isinstance(out.get(path[0]), dict):
            out[path[0]].pop(path[1], None)
    return out


def uncached(record: Mapping[str, Any]) -> int:
    """LLM steps of a record that were not served from the cache."""
    return sum(
        1 for s in record.get("steps") or [] if s.get("phase") != "code" and not s.get("cached")
    )


def compare(first: Sequence[Mapping[str, Any]], second: Sequence[Mapping[str, Any]]) -> list[str]:
    """Problems: a different count or order, an uncached call in the second pass, or a record
    that differs outside EXCLUDED."""
    if len(first) != len(second):
        return [f"record count {len(first)} != {len(second)}"]
    problems = []
    for a, b in zip(first, second, strict=True):
        qid = a.get("question_id") or a.get("run_id", "?")
        if a.get("question_id") != b.get("question_id"):
            problems.append(f"{qid}: question order differs ({b.get('question_id')})")
            continue
        llm = (b.get("tokens") or {}).get("llm_calls", 0)
        if uncached(b) or (llm and b.get("cache") != "hit"):  # 0 calls: no cache state (None)
            problems.append(f"{qid}: second pass made {uncached(b)} uncached call(s)")
        if without_excluded(a) != without_excluded(b):
            keys = sorted(
                k
                for k in set(without_excluded(a)) | set(without_excluded(b))
                if without_excluded(a).get(k) != without_excluded(b).get(k)
            )
            problems.append(f"{qid}: differs outside the excluded fields in {keys}")
    return problems


def _load(path: Path) -> list[dict[str, Any]]:
    return [json.loads(x) for x in path.read_text().splitlines() if x.strip()]


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawTextHelpFormatter)
    ap.add_argument("--first", type=Path, required=True)
    ap.add_argument("--second", type=Path, required=True)
    ns = ap.parse_args(argv)
    first, second = _load(ns.first), _load(ns.second)
    problems = compare(first, second)
    calls = sum(uncached(r) for r in second)
    print(f"first {len(first)} records; second {len(second)} records, {calls} uncached calls")
    for p in problems:
        print(f"  {p}")
    print("reproducible from the cache" if not problems else f"{len(problems)} problem(s)")
    return 0 if not problems else 1


if __name__ == "__main__":
    sys.exit(main())
