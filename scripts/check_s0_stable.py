"""S0 stability check (S12a, owner decision 20 Oct 2026; reused in S12b; baselines since S13c).

Re-runs S0 (no LLM, free) into a temporary directory and compares every record with the
committed ``eval/runs/s0/`` records. Exactly one field is excluded: ``EXCLUDED`` (wall-clock
latency, different on every run). Everything else must be equal. Committed files are never
touched.

By default the fresh run is compared with the NEWEST versioned baseline under
``eval/runs/s0/baseline/<session>/`` (S13c, owner decision: a baseline is written after approved
linker changes; the pilot S0 records are never rewritten). ``--pilot`` compares with the
committed pilot records in ``eval/runs/s0/`` instead. With no baseline directory, the pilot
records are the reference.

    uv run python scripts/check_s0_stable.py [--pilot]
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
BASELINES = COMMITTED / "baseline"
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


def reference(pilot: bool = False) -> Path:
    """The directory the fresh run is compared with: the newest versioned baseline (directory
    names sort by session, e.g. s13c < s14), or the pilot records with ``pilot`` or when there
    is no baseline."""
    if not pilot and BASELINES.is_dir():
        dirs = sorted(d for d in BASELINES.iterdir() if d.is_dir())
        if dirs:
            return dirs[-1]
    return COMMITTED


def main(argv: list[str] | None = None) -> int:
    import argparse

    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawTextHelpFormatter)
    ap.add_argument("--pilot", action="store_true", help="compare with the pilot S0 records")
    ns = ap.parse_args(argv)
    ref = reference(ns.pilot)
    print(f"reference: {ref.relative_to(ROOT).as_posix()}")
    sys.path.insert(0, str(ROOT / "eval"))
    from systems import s0

    with tempfile.TemporaryDirectory() as tmp:
        s0.main(["--out", tmp])
        bad = 0
        for system in SYSTEMS:
            name = f"{system}-dev.jsonl"
            a, b = _load(ref / name), _load(Path(tmp) / name)
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
