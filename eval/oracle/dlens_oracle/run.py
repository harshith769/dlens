"""Run the whole oracle on one corpus and assemble the results document (oracle-design.md §7).

The document is deterministic for a fixed seed and fixed tool versions, except for ``runtime_s``.
It holds no absolute paths: files are cited relative to the corpus project.
"""

import re
import time
from collections import Counter
from collections.abc import Iterable
from importlib.metadata import version
from pathlib import Path
from typing import Any

import duckdb

from dlens_oracle import controls, perturb
from dlens_oracle import modes as modes_mod
from dlens_oracle import thresholds as th
from dlens_oracle.build import Corpus, Warehouse, compiled
from dlens_oracle.e2e import E2EResult, e2e_check
from dlens_oracle.gold import Gold, load_gold

ORACLE_VERSION = 1
VOLATILE = ("runtime_s",)  # keys that differ between identical runs


class NotDeterministic(RuntimeError):
    """Control (a) failed: the base build differs between two runs. Nothing was perturbed."""


def _line(lines: list[str], pattern: str, start: int = 0) -> tuple[int, str] | None:
    rx = re.compile(pattern, re.IGNORECASE)
    for i in range(start, len(lines)):
        if rx.search(lines[i]):
            return i + 1, lines[i].strip()
    return None


def citation(corpus: Corpus, gold: Gold, case: perturb.Case) -> dict[str, Any]:
    """Text lookup for the owner's spot-check: the JOIN line of the key, the target's line.

    The key is found as ``alias.key`` on an ON / AND line, where the alias is the gold row's
    ``via`` CTE or the parent table's alias in FROM / JOIN. The target is looked up in the final
    SELECT first (the last line that starts with ``select``).
    """
    model, target = case.dst.rsplit(".", 1)
    parent, key = case.src.split(".", 1)
    m = corpus.models[model]
    lines = m.sql.splitlines()
    aliases = sorted(gold.via.get((case.src, model), set()))
    found = re.search(rf'"{re.escape(parent)}"\s+as\s+(\w+)', m.sql, re.IGNORECASE)
    aliases += [found.group(1)] if found else []
    join = next(
        (
            hit
            for alias in aliases
            if (hit := _line(lines, rf"^\s*(on|and)\b.*\b{re.escape(alias)}\.{re.escape(key)}\b"))
        ),
        None,
    ) or _line(lines, rf"^\s*(on|and)\b.*\b{re.escape(key)}\b")
    final = max((i for i, text in enumerate(lines) if re.match(r"select\b", text)), default=0)
    target_rx = [rf"\bas\s+{re.escape(target)}\b", rf"^\s*(\w+\.)?{re.escape(target)}\s*,?\s*$"]
    src = next((hit for rx in target_rx if (hit := _line(lines, rx, final))), None) or next(
        (hit for rx in target_rx if (hit := _line(lines, rx))), None
    )
    out: dict[str, Any] = {"file": m.path}
    if join:
        out["join_line"] = {"line": join[0], "sql": join[1]}
    if src:
        out["target_line"] = {"line": src[0], "sql": src[1]}
    return out


def _labels_table(results: list[perturb.LocalResult]) -> dict[str, dict[str, int]]:
    table: dict[str, Counter[str]] = {}
    for r in results:
        for group, cases in (("confirmed", r.confirmed), ("not_observed", r.category_b)):
            for c in cases:
                for label in c.labels:
                    table.setdefault(label, Counter())[group] += 1
    return {k: {"confirmed": v["confirmed"], "not_observed": v["not_observed"]}
            for k, v in sorted(table.items())}  # fmt: skip


def _thresholds_doc(
    wh: Warehouse, spec: th.ThresholdFile, results: list[perturb.LocalResult]
) -> list[dict[str, Any]]:
    out = []
    for t in spec.thresholds:
        _, values = th.run_probe(wh, t)
        crossings = {r.column: r.crossings[t.id] for r in results if t.id in r.crossings}
        out.append(
            {
                "id": t.id,
                "model": t.model,
                "lines": list(t.lines),
                "predicate": t.predicate,
                "clause": t.clause,
                "cutoffs": list(t.cutoffs),
                "nearest": th.nearest(values, t.cutoffs),
                "crossings": crossings,
                "total_crossings": sum(
                    n for by_mode in crossings.values() for n in by_mode.values()
                ),
            }
        )
    return out


def _e2e_doc(results: list[E2EResult]) -> dict[str, Any]:
    rows: list[dict[str, Any]] = [
        {
            "column": r.column,
            "changed": len(r.changed),
            "closure_direct": len(r.closure_direct),
            "closure_all": len(r.closure_all),
            "observed_in_direct_closure": len(set(r.changed) & r.closure_direct),
            "category_a": r.category_a,
            "indirect_only": r.indirect_only,
            "unobserved_explained": len(r.unobserved_explained),
            "unobserved_unexplained": r.unobserved_unexplained,
            **({"errors": r.errors} if r.errors else {}),
        }
        for r in results
    ]
    return {
        "summary": {
            "seed_columns": len(rows),
            "changed": sum(r["changed"] for r in rows),
            "closure_direct": sum(r["closure_direct"] for r in rows),
            "closure_all": sum(r["closure_all"] for r in rows),
            "observed_in_direct_closure": sum(r["observed_in_direct_closure"] for r in rows),
            "category_a": sum(len(r["category_a"]) for r in rows),
            "indirect_only": sum(len(r["indirect_only"]) for r in rows),
            "unobserved_explained": sum(r["unobserved_explained"] for r in rows),
            "unobserved_unexplained": sum(len(r["unobserved_unexplained"]) for r in rows),
            "errors": sum(len(r.get("errors", {})) for r in rows),
        },
        "columns": rows,
    }


def run_oracle(
    corpus_dir: Path,
    spec_path: Path,
    thresholds_path: Path = th.THRESHOLDS,
    seed: int = modes_mod.SEED,
    tables: Iterable[str] | None = None,
    seeds: Iterable[str] | None = None,
) -> dict[str, Any]:
    """Compile, build, run controls, the local and the end-to-end check; return the document."""
    clock: dict[str, float] = {}
    start = time.perf_counter()
    gold = load_gold(spec_path)
    spec = th.load(thresholds_path)
    with compiled(corpus_dir) as corpus:
        clock["dbt_compile"] = time.perf_counter() - start
        wh = Warehouse(corpus)
        try:
            return _run(corpus, wh, gold, spec, seed, tables, seeds, clock, start)
        finally:
            wh.close()


def _run(
    corpus: Corpus,
    wh: Warehouse,
    gold: Gold,
    spec: th.ThresholdFile,
    seed: int,
    tables: Iterable[str] | None,
    seeds: Iterable[str] | None,
    clock: dict[str, float],
    start: float,
) -> dict[str, Any]:
    differing = controls.determinism(corpus, wh)
    if differing:
        raise NotDeterministic(f"base build differs between two runs in: {differing}")
    t = time.perf_counter()
    order = controls.row_order(wh, seed)
    clock["controls"] = time.perf_counter() - t

    sql = {name: m.sql for name, m in corpus.models.items()}
    t = time.perf_counter()
    local, dead_ends = perturb.local_check(wh, gold, order, spec, seed, tables)
    clock["local"] = time.perf_counter() - t
    local_b = {(c.src, c.dst) for r in local for c in r.category_b}
    t = time.perf_counter()
    e2e = e2e_check(wh, gold, local_b, seed, seeds)
    clock["e2e"] = time.perf_counter() - t

    cat_b = [c for r in local for c in r.category_b]
    tagged = [c for c in cat_b if c.tag]
    rpj = [c for c in tagged if c.tag == "row_preserving_join"]
    no_gold_out = sorted(
        r.column
        for r in local
        if not gold.one_hop(r.column) and not r.confirmed and not r.category_a
    )
    errors = [
        {"column": r.column, "child": child, "mode": mode, "error": text}
        for r in local
        for child, by_mode in sorted(r.errors.items())
        for mode, text in sorted(by_mode.items())
    ]
    clock["total"] = time.perf_counter() - start
    return {
        "oracle": {
            "version": ORACLE_VERSION,
            "corpus": corpus.catalog,
            "seed": seed,
            "dbt_core": version("dbt-core"),
            "dbt_duckdb": version("dbt-duckdb"),
            "duckdb": duckdb.__version__,
        },
        "runtime_s": {k: round(v, 1) for k, v in clock.items()},
        "controls": {
            "determinism_failures": differing,
            "order_sensitive": dict(sorted(order.columns.items())),
        },
        "drift": {
            "depends_on": perturb.depends_on_drift(corpus, gold),
            "gold_pairs_into_non_children": [c.as_dict() for r in local for c in r.drift],
        },
        "thresholds": {
            "uncovered": th.uncovered(sql, spec),
            "stale": th.stale(sql, spec),
            "items": _thresholds_doc(wh, spec, local),
        },
        "local": {
            "summary": {
                "columns_perturbed": len(local),
                "runs": sum(len(r.modes) for r in local),
                "gold_pairs": sum(len(r.confirmed) + len(r.category_b) for r in local),
                "confirmed": sum(len(r.confirmed) for r in local),
                "category_a": sum(len(r.category_a) for r in local),
                "category_b": len(cat_b),
                "category_b_tagged": dict(sorted(Counter(c.tag for c in tagged).items())),
                "category_b_untagged": len(cat_b) - len(tagged),
                "indirect_only": sum(len(r.indirect_only) for r in local),
                "errors": len(errors),
                "dead_ends": len(dead_ends),
            },
            "by_label": _labels_table(local),
            "category_a": [c.as_dict() for r in local for c in r.category_a],
            "category_b": [c.as_dict() for c in cat_b],
            "row_preserving_join_by_model": dict(
                sorted(Counter(c.dst.rsplit(".", 1)[0] for c in rpj).items())
            ),
            "spot_check": [
                {**c.as_dict(), **citation(corpus, gold, c)}
                for c in perturb.spot_check_sample(rpj, seed)
            ],
            "indirect_only": [c.as_dict() for r in local for c in r.indirect_only],
            "errors": errors,
            "dead_ends": dead_ends,
            "no_gold_out_edge": no_gold_out,
            "confirmed": [f"{c.src} -> {c.dst}" for r in local for c in r.confirmed],
        },
        "e2e": _e2e_doc(e2e),
    }


def comparable(doc: dict[str, Any]) -> dict[str, Any]:
    """The document without the keys that differ between identical runs."""
    return {k: v for k, v in doc.items() if k not in VOLATILE}
