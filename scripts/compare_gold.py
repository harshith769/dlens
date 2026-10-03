"""Compare dlens lineage edges with a corpus gold spec.

    uv run python scripts/compare_gold.py corpora/synthetic_shop            # gate F1 >= 0.95
    uv run python scripts/compare_gold.py corpora/jaffle_shop --counts-only

Ingests a temporary copy of the corpus so the repo stays free of target/ and *.duckdb.
Exits 1 if F1 is below the gate.
"""

import argparse
import shutil
import sys
import tempfile
from collections import Counter
from pathlib import Path

import yaml

from dlens.ingest import ingest
from dlens.lineage import LineageResult, compare, extract_lineage


def run(corpus: Path) -> LineageResult:
    with tempfile.TemporaryDirectory() as tmp:
        project = Path(tmp) / corpus.name
        shutil.copytree(
            corpus, project, ignore=shutil.ignore_patterns("target", "*.duckdb", "logs")
        )
        return extract_lineage(ingest(project), project)


def print_counts(result: LineageResult) -> None:
    kinds = Counter(str(e.kind) for e in result.edges)
    print(f"edges: {len(result.edges)}  " + "  ".join(f"{k}={v}" for k, v in sorted(kinds.items())))
    print(f"low-confidence edges: {sum(e.confidence == 'low' for e in result.edges)}")
    print(f"model-level citations: {sum(e.model_level_citation for e in result.edges)}")
    print(f"depends_on edges: {len(result.depends_on)}")
    for uid, p in result.parse_report.items():
        extra = f"  ({p.reason})" if p.reason else ""
        window = f"  [{len(p.deferred_indirect)} deferred WINDOW]" if p.deferred_indirect else ""
        print(f"  {p.quality:<10} {uid}{window}{extra}")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("corpus", type=Path)
    ap.add_argument("--gate", type=float, default=0.95)
    ap.add_argument("--counts-only", action="store_true")
    args = ap.parse_args()

    result = run(args.corpus)
    print_counts(result)
    if args.counts_only:
        return 0

    gold = yaml.safe_load((args.corpus / "lineage_spec.yml").read_text())["edges"]
    gold = [g for g in gold if g.get("phase", "v0.1") == "v0.1"]
    r = compare(result.edges, gold)
    print(f"\ngold edges: {len(gold)}  matched: {r.matched}")
    print(
        f"precision {r.precision:.3f}  recall {r.recall:.3f}  F1 {r.f1:.3f}  "
        f"kind accuracy {r.kind_accuracy:.3f}"
    )
    for title, rows in (
        ("MISSING", r.missing),
        ("EXTRA", r.extra),
        ("KIND MISMATCH (gold, engine)", r.kind_mismatches),
    ):
        print(f"\n{title}: {len(rows)}")
        for row in rows:
            print("  " + "  ".join(row))
    ok = r.f1 >= args.gate
    print(f"\ngate F1 >= {args.gate}: {'PASS' if ok else 'FAIL'}")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
