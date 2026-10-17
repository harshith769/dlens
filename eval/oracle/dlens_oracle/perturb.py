"""Perturbation oracle: local (one-hop) and end-to-end checks against the gold (oracle-design.md).

    uv run python scripts/run_oracle.py            # synthetic_shop -> eval/oracle/results/

Perturb a column, re-run compiled SQL in DuckDB, record which columns change, compare with
lineage_spec.yml. Category A (changed, not in gold) is a spec bug or SQL drift for the owner to
decide. Category B (gold, not observed) is auto-tagged when the reason is certain, else listed.
"""

import random
import re
from collections.abc import Iterable
from dataclasses import dataclass, field
from typing import Any

import duckdb

from dlens_oracle import modes as modes_mod
from dlens_oracle import thresholds as th
from dlens_oracle.build import BASE, Corpus, Fingerprint, Warehouse
from dlens_oracle.controls import OrderSensitivity
from dlens_oracle.gold import Gold, is_indirect_label

TAGS = ("sort_no_limit", "row_preserving_join", "constant_target", "filter_not_crossed")
ORDERED_AGGREGATES = ("string_agg", "array_agg", "list", "group_concat", "listagg", "first", "last")


# ------------------------------------------------------------------------------------ one column
@dataclass
class ColumnRun:
    """Every mode applied to one column of one table, with its direct children re-run."""

    column: str  # short id, table.column
    sql_type: str
    modes: list[str] = field(default_factory=list)  # modes that applied
    # child column -> modes that changed it
    changed: dict[str, list[str]] = field(default_factory=dict)
    # child model -> modes in which its row count changed
    row_count_changed: dict[str, list[str]] = field(default_factory=dict)
    # child model -> {mode: error text}
    errors: dict[str, dict[str, str]] = field(default_factory=dict)
    # threshold id -> {mode: crossings}
    crossings: dict[str, dict[str, int]] = field(default_factory=dict)


def perturb_column(
    wh: Warehouse,
    table: str,
    column: str,
    base: dict[str, Fingerprint],
    probes: dict[str, tuple[th.Threshold, th.Outcomes]],
    seed: int,
) -> ColumnRun:
    """Apply each mode of ``table.column`` in turn and re-run the table's direct children."""
    sql_type = wh.types(table)[column]
    run = ColumnRun(f"{table}.{column}", sql_type)
    values = wh.column_values(table, column)
    for mode in modes_mod.modes_for(sql_type):
        new = modes_mod.apply(mode, sql_type, values, run.column, seed)
        if new is None:
            continue
        run.modes.append(mode)
        wh.write_column(table, column, new)
        try:
            for child in wh.corpus.children[table]:
                try:
                    fp = wh.model_fingerprint(child)
                except duckdb.Error as exc:
                    run.errors.setdefault(child, {})[mode] = str(exc).splitlines()[0]
                    continue
                if fp.rows != base[child].rows:
                    run.row_count_changed.setdefault(child, []).append(mode)
                for name in fp.changed(base[child]):
                    run.changed.setdefault(f"{child}.{name}", []).append(mode)
            for tid, (threshold, before) in probes.items():
                now, _ = th.run_probe(wh, threshold)
                run.crossings.setdefault(tid, {})[mode] = th.crossings(before, now)
        finally:
            wh.restore(table)
    return run


# ------------------------------------------------------------------------------- classification
@dataclass
class Case:
    """One (from, to) pair seen by the local check."""

    src: str
    dst: str
    labels: list[str]  # gold labels (direct kind / indirect types); empty for category A
    modes: list[str] = field(default_factory=list)  # modes that changed dst
    row_count_modes: list[str] = field(default_factory=list)  # modes that changed dst's row count
    tag: str | None = None  # category-B auto-tag
    note: str = ""
    order_sensitive: list[str] = field(default_factory=list)  # control (b) parents

    def as_dict(self) -> dict[str, Any]:
        out: dict[str, Any] = {"from": self.src, "to": self.dst, "labels": self.labels}
        for key in ("modes", "row_count_modes", "order_sensitive"):
            if getattr(self, key):
                out[key] = getattr(self, key)
        if self.tag:
            out["tag"] = self.tag
        if self.note:
            out["note"] = self.note
        return out


def _limit(sql: str) -> bool:
    return re.search(r"\blimit\b", sql, re.IGNORECASE) is not None


def _balanced(sql: str, start: int) -> str:
    """Text from the '(' at ``start`` to its matching ')'."""
    depth = 0
    for i in range(start, len(sql)):
        depth += {"(": 1, ")": -1}.get(sql[i], 0)
        if depth == 0:
            return sql[start : i + 1]
    return sql[start:]


def ordered_contexts(sql: str) -> list[str]:
    """ORDER BY parts of window OVER (…) clauses and of ordered aggregates (text scan)."""
    out = []
    pattern = r"\bover\s*\(|\b(?:" + "|".join(ORDERED_AGGREGATES) + r")\s*\("
    for m in re.finditer(pattern, sql, re.IGNORECASE):
        body = _balanced(sql, m.end() - 1)
        order = re.search(r"\border\s+by\b(.*)", body, re.IGNORECASE | re.DOTALL)
        if order:
            out.append(order.group(1))
    return out


def sort_no_limit(sql: str, column_name: str) -> bool:
    """Amendment 2: no LIMIT, and the column is in no window / ordered-aggregate ORDER BY."""
    if _limit(sql):
        return False
    word = re.compile(rf"\b{re.escape(column_name)}\b", re.IGNORECASE)
    return not any(word.search(part) for part in ordered_contexts(sql))


@dataclass
class LocalResult:
    column: str
    children: list[str]
    confirmed: list[Case]
    category_a: list[Case]
    category_b: list[Case]
    indirect_only: list[Case]
    drift: list[Case]  # gold pairs into a model that, per the manifest, doesn't read the table
    errors: dict[str, dict[str, str]]
    crossings: dict[str, dict[str, int]]
    modes: list[str]


def classify(
    run: ColumnRun,
    table: str,
    gold: Gold,
    wh: Warehouse,
    order: OrderSensitivity,
    thresholds_by_model: dict[str, list[th.Threshold]],
) -> LocalResult:
    children = wh.corpus.children[table]
    expected = {t: labels for t, labels in gold.one_hop(run.column).items()}
    child_set = set(children)
    confirmed, cat_a, cat_b, indirect_only, drift = [], [], [], [], []
    for dst, used in sorted(run.changed.items()):
        model = dst.rsplit(".", 1)[0]
        case = Case(run.column, dst, sorted(expected.get(dst, set())), sorted(used))
        case.row_count_modes = sorted(run.row_count_changed.get(model, []))
        case.order_sensitive = order.columns.get(dst, [])
        if dst in expected:
            confirmed.append(case)
            if not any(not is_indirect_label(lb) for lb in case.labels):
                indirect_only.append(case)
        else:
            cat_a.append(case)
    for dst in sorted(set(expected) - set(run.changed)):
        model = dst.rsplit(".", 1)[0]
        case = Case(run.column, dst, sorted(expected[dst]))
        if model not in child_set:
            case.note = f"gold pair into {model}, which does not read {table} (manifest)"
            drift.append(case)
            continue
        case.tag, case.note = _tag(case, run, table, gold, wh, thresholds_by_model)
        cat_b.append(case)
    return LocalResult(
        run.column,
        children,
        confirmed,
        cat_a,
        cat_b,
        indirect_only,
        drift,
        run.errors,
        run.crossings,
        run.modes,
    )


def _value_modes(run: ColumnRun) -> list[str]:
    return [m for m in run.modes if m not in modes_mod.MULTISET_PRESERVING]


def _tag(
    case: Case,
    run: ColumnRun,
    table: str,
    gold: Gold,
    wh: Warehouse,
    thresholds_by_model: dict[str, list[th.Threshold]],
) -> tuple[str | None, str]:
    model, target = case.dst.rsplit(".", 1)
    errors = run.errors.get(model, {})
    value_modes = _value_modes(run)
    if value_modes and all(m in errors for m in value_modes):
        return None, "every value-changing mode errored: " + "; ".join(
            f"{m}: {errors[m]}" for m in value_modes
        )
    labels = set(case.labels)
    rows_kept = not run.row_count_changed.get(model) and not errors
    column_name = run.column.split(".", 1)[1]
    if labels == {"SORT"}:
        row_set = (run.column, model, "SORT") in gold.row_set
        if row_set and sort_no_limit(wh.corpus.models[model].sql, column_name):
            return "sort_no_limit", ""
        return None, "SORT edge not covered by sort_no_limit (LIMIT, or an ordered context)"
    if labels == {"JOIN"} and rows_kept:
        own = {f for f in gold.direct_inputs(case.dst) if f.split(".", 1)[0] == table}
        if not own:
            return "row_preserving_join", ""
        return None, f"JOIN edge, row count kept, but target reads {sorted(own)}"
    if rows_kept and _distinct(wh, model, target) <= 1:
        return "constant_target", ""
    if labels and labels <= {"FILTER", "CONDITIONAL"}:
        relevant = [
            t
            for t in thresholds_by_model.get(model, [])
            if t.clause in labels and run.column in t.inputs
        ]
        if relevant and all(sum(run.crossings.get(t.id, {}).values()) == 0 for t in relevant):
            return "filter_not_crossed", ""
        if relevant:
            return None, "filter crossed: " + ", ".join(
                f"{t.id}={sum(run.crossings.get(t.id, {}).values())}" for t in relevant
            )
    return None, ""


def _distinct(wh: Warehouse, model: str, column: str) -> int:
    sql = (
        f'SELECT count(DISTINCT "{column}") + max(CASE WHEN "{column}" IS NULL THEN 1 ELSE 0 END) '
    )
    sql += f'FROM {BASE}."{model}"'
    row = wh.con.execute(sql).fetchone()
    return int(row[0] or 0) if row else 0


# ---------------------------------------------------------------------------------- local check
def local_check(
    wh: Warehouse,
    gold: Gold,
    order: OrderSensitivity,
    spec: th.ThresholdFile,
    seed: int = modes_mod.SEED,
    tables: Iterable[str] | None = None,
) -> tuple[list[LocalResult], list[str]]:
    """(results per perturbed column, dead-end columns with no child to observe)."""
    corpus = wh.corpus
    base = {m: wh.table_fingerprint(m, BASE) for m in corpus.models}
    by_input = spec.by_input()
    by_model: dict[str, list[th.Threshold]] = {}
    for t in spec.thresholds:
        by_model.setdefault(t.model, []).append(t)
    results, dead_ends = [], []
    for table in tables if tables is not None else [*corpus.seeds, *corpus.models]:
        for column in wh.types(table):
            short = f"{table}.{column}"
            if not corpus.children[table]:
                dead_ends.append(short)
                continue
            probes = {t.id: (t, th.run_probe(wh, t)[0]) for t in by_input.get(short, [])}
            run = perturb_column(wh, table, column, base, probes, seed)
            results.append(classify(run, table, gold, wh, order, by_model))
    return results, dead_ends


# ------------------------------------------------------------------------------------- helpers
def depends_on_drift(corpus: Corpus, gold: Gold) -> list[str]:
    """Models whose manifest parents differ from the spec's depends_on (SQL drift)."""
    out = []
    for name, model in corpus.models.items():
        spec = set(gold.depends_on.get(name, []))
        if spec != set(model.parents):
            out.append(f"{name}: manifest {sorted(model.parents)} vs spec {sorted(spec)}")
    return out


def spot_check_sample(cases: list[Case], seed: int, k: int = 10) -> list[Case]:
    """k cases chosen with the fixed seed (amendment: owner's row_preserving_join spot-check)."""
    pool = sorted(cases, key=lambda c: (c.src, c.dst))
    return sorted(random.Random(f"{seed}:spot_check").sample(pool, min(k, len(pool))),
                  key=lambda c: (c.src, c.dst))  # fmt: skip
