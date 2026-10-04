"""Compare dlens lineage edges with a corpus gold spec.

    uv run python scripts/compare_gold.py corpora/synthetic_shop            # gate F1 >= 0.95
    uv run python scripts/compare_gold.py corpora/jaffle_shop --counts-only
    uv run python scripts/compare_gold.py corpora/synthetic_shop --indirect   # + indirect F1 >= 0.90

Ingests a temporary copy of the corpus so the repo stays free of target/ and *.duckdb.
Exits 1 if F1 is below the gate (with --indirect, also if indirect F1 is below its gate).
"""

import argparse
import shutil
import sys
import tempfile
from collections import Counter
from pathlib import Path

import yaml

from dlens.gold_spec import INDIRECT_TYPES, expand_indirect
from dlens.ingest import ingest
from dlens.lineage import LineageResult, compare, compare_indirect, extract_lineage, short_id
from dlens.lineage.gold import Score


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


def _row(name: str, s: Score) -> str:
    return (
        f"  {name:<34} engine {s.engine:>4}  gold {s.gold:>4}  matched {s.matched:>4}  "
        f"P {s.precision:.3f}  R {s.recall:.3f}  F1 {s.f1:.3f}"
    )


def report_indirect(result: LineageResult, spec: dict) -> float:  # type: ignore[type-arg]
    """Engine indirect edges vs dlens.gold_spec.expand_indirect(gold) (ADR 0020). Returns F1."""
    models = {m: list(v["columns"]) for m, v in spec["models"].items()}
    direct = {(e["from"], e["to"]) for e in spec["edges"]}
    pairs = expand_indirect(spec["indirect_edges"], models, direct).pairs
    gold = [(p.from_column, p.to_column, p.type) for p in pairs]
    r = compare_indirect(result.indirect, gold)
    print(
        f"\nINDIRECT (engine vs expanded gold; gold {len(gold)} triples, "
        f"{len({(f, t) for f, t, _ in gold})} distinct pairs)"
    )
    print(_row("overall", r.overall))
    for kind in INDIRECT_TYPES:
        if kind in r.by_type:
            print(_row(kind, r.by_type[kind]))
    print("\nper target model:")
    for model, s in r.by_model.items():
        print(_row(model, s))
    low = sorted(e for e in result.indirect if e.confidence == "low")
    by_model = Counter(short_id(e.to_column).split(".")[0] for e in low)
    print(f"\nLOW-confidence indirect edges: {len(low)}  {dict(sorted(by_model.items()))}")
    for title, rows in (
        ("MISSING (gold, not engine)", r.missing),
        ("EXTRA (engine, not gold)", r.extra),
    ):
        print(f"\n{title}: {len(rows)}")
        for row in rows:
            print("  " + "  ".join(row))
    return r.overall.f1


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("corpus", type=Path)
    ap.add_argument("--gate", type=float, default=0.95)
    ap.add_argument("--counts-only", action="store_true")
    ap.add_argument("--indirect", action="store_true", help="also gate indirect edges")
    ap.add_argument("--indirect-gate", type=float, default=0.90)
    args = ap.parse_args()

    result = run(args.corpus)
    print_counts(result)
    if args.counts_only:
        return 0

    spec = yaml.safe_load((args.corpus / "lineage_spec.yml").read_text())
    gold = [g for g in spec["edges"] if g.get("phase", "v0.1") == "v0.1"]
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
    if args.indirect:
        f1 = report_indirect(result, spec)
        ok_indirect = f1 >= args.indirect_gate
        print(f"\nindirect gate F1 >= {args.indirect_gate}: {'PASS' if ok_indirect else 'FAIL'}")
        ok = ok and ok_indirect
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
