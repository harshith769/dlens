"""Run the perturbation oracle on a corpus and write its results and report (S05, A4).

    uv run python scripts/run_oracle.py                      # synthetic_shop (make oracle)
    uv run python scripts/run_oracle.py --check              # compare with the committed results

Offline and free: dbt seed + compile in a temp dir, then DuckDB in memory. No LLM call.
Writes eval/oracle/results/<corpus>.json and corpora/<corpus>/ORACLE_REPORT.md. Exits 1 if any
category-A case or untagged category-B case lacks an owner decision in oracle_exceptions.yml,
2 if the base build is not deterministic (nothing is perturbed then).
See docs/plans/oracle-design.md and docs/explain/oracle.md.
"""

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).parents[1]
sys.path.insert(0, str(ROOT / "eval" / "oracle"))

from dlens_oracle.report import load_exceptions, render, undecided  # noqa: E402
from dlens_oracle.run import NotDeterministic, comparable, run_oracle  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--corpus", type=Path, default=ROOT / "corpora" / "synthetic_shop")
    parser.add_argument("--check", action="store_true", help="compare, don't write")
    args = parser.parse_args()
    corpus = args.corpus.resolve()
    out = ROOT / "eval" / "oracle" / "results" / f"{corpus.name}.json"
    report = corpus / "ORACLE_REPORT.md"
    exceptions = load_exceptions(corpus / "oracle_exceptions.yml")
    try:
        doc = run_oracle(corpus, corpus / "lineage_spec.yml")
    except NotDeterministic as exc:
        print(f"STOP: control (a) failed, nothing perturbed: {exc}", file=sys.stderr)
        return 2
    if args.check:
        committed = json.loads(out.read_text())
        same = comparable(committed) == comparable(json.loads(json.dumps(doc)))
        print(
            "results match the committed file" if same else "results DIFFER from the committed file"
        )
        return 0 if same else 1
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(doc, indent=1, sort_keys=False) + "\n")
    report.write_text(render(doc, exceptions))
    s, e = doc["local"]["summary"], doc["e2e"]["summary"]
    print(f"wall time {doc['runtime_s']['total']} s ({doc['runtime_s']})")
    print(
        f"local: {s['confirmed']} confirmed, A={s['category_a']}, B={s['category_b']} "
        f"(tagged {s['category_b_tagged']}, owner {s['category_b_untagged']}), "
        f"indirect-only {s['indirect_only']}, errors {s['errors']}"
    )
    print(
        f"e2e: A={e['category_a']}, indirect-only {e['indirect_only']}, unobserved explained "
        f"{e['unobserved_explained']}, unexplained {e['unobserved_unexplained']}"
    )
    pending = undecided(doc, exceptions)
    print(f"undecided: A={len(pending['category_a'])}, B={len(pending['category_b'])}")
    print(f"wrote {out.relative_to(ROOT)} and {report.relative_to(ROOT)}")
    return 1 if pending["category_a"] or pending["category_b"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
