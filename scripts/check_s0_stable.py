"""S0 stability check (S12a, owner decision 20 Oct 2026; reused in S12b).

Re-runs S0 (no LLM, free) into a temporary directory and compares every record with the
committed ``eval/runs/s0/`` records. Exactly one field is excluded: ``EXCLUDED`` (wall-clock
latency, different on every run). Everything else must be equal. Committed files are never
touched.

    uv run python scripts/check_s0_stable.py
"""

from __future__ import annotations

import json
import sys
import tempfile
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
COMMITTED = ROOT / "eval" / "runs" / "s0"
SYSTEMS = ("s0-gold", "s0-linked")
EXCLUDED = ("timings", "total_ms")  # the one field allowed to differ


def without_excluded(record: Mapping[str, Any]) -> dict[str, Any]:
    out = json.loads(json.dumps(record))
    parent, key = EXCLUDED
    if isinstance(out.get(parent), dict):
        out[parent].pop(key, None)
    return out


def compare(
    committed: Sequence[Mapping[str, Any]], fresh: Sequence[Mapping[str, Any]]
) -> list[str]:
    """Problems found: a different record count, or a record that differs outside EXCLUDED."""
    if len(committed) != len(fresh):
        return [f"record count {len(committed)} != {len(fresh)}"]
    return [
        f"record {i} ({a.get('run_id', '?')}) differs outside {'.'.join(EXCLUDED)}"
        for i, (a, b) in enumerate(zip(committed, fresh, strict=True))
        if without_excluded(a) != without_excluded(b)
    ]


def _load(path: Path) -> list[dict[str, Any]]:
    return [json.loads(x) for x in path.read_text().splitlines() if x.strip()]


def main() -> int:
    sys.path.insert(0, str(ROOT / "eval"))
    from systems import s0

    with tempfile.TemporaryDirectory() as tmp:
        s0.main(["--out", tmp])
        bad = 0
        for system in SYSTEMS:
            name = f"{system}-dev.jsonl"
            a, b = _load(COMMITTED / name), _load(Path(tmp) / name)
            problems = compare(a, b)
            moved = sum(
                (x.get(EXCLUDED[0]) or {}).get(EXCLUDED[1])
                != (y.get(EXCLUDED[0]) or {}).get(EXCLUDED[1])
                for x, y in zip(a, b, strict=False)
            )
            print(
                f"{system}: {len(a)} records; {len(problems)} differ outside "
                f"{'.'.join(EXCLUDED)}; {moved} differ in it"
            )
            for p in problems[:10]:
                print(f"  {p}")
            bad += len(problems)
    return 1 if bad else 0


if __name__ == "__main__":
    raise SystemExit(main())
