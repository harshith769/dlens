"""Column pools for the question splits (S09, docs/plans/questions-design.md §2).

uv run python scripts/question_pools.py          # writes eval/questions/pools.yml
uv run python scripts/question_pools.py --check  # exit 1 if the file on disk is stale

Every column of lineage_spec.yml (seeds and models) goes to the dev or the test pool BEFORE any
question is generated. Stratum = (hop bucket, rarest trap); a small trap (<= SMALL_TRAP columns)
is one stratum across buckets, so its columns split between dev and test (owner Q5: 1/1). Inside a stratum, columns are ordered
by sha256(SALT + id); the 18 existing v0.2 dev targets (and the 3 other columns their texts
name) go to dev first and count toward the stratum's
dev quota, max(forced, round(0.30 n)), at least 1 when n >= 2; a 1-column stratum goes to dev when
its hash fraction is below 0.30. The file lists column ids and splits only, never question text.

Sources: lineage_spec.yml and traps.yml (hand-written gold) and the dev.jsonl targets. The graph,
the parser and the linker are never loaded. The coverage check fails, naming the requirement, if
the dev pool cannot supply the count table; it never borrows a test column.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import sys
from collections import Counter, defaultdict
from collections.abc import Mapping
from pathlib import Path
from typing import Any

import yaml

from dlens import gold_spec as gs

ROOT = Path(__file__).parents[1]
SS = ROOT / "corpora" / "synthetic_shop"
SPEC = SS / "lineage_spec.yml"
TRAPS = SS / "traps.yml"
DEV = ROOT / "eval" / "questions" / "dev.jsonl"
OUT = ROOT / "eval" / "questions" / "pools.yml"
SALT = "s09-pools-v1:"
SHARE = 0.30
SMALL_TRAP = 5  # traps naming this many columns or fewer are stratified by trap alone
# The 19 distinct targets of the 20 v0.2 dev questions (dev-11 and dev-17 share one; dev-19's
# does not exist, so 18 are forced). Pinned here so the pools never
# depend on the current contents of dev.jsonl.
V02_TARGETS = (
    "stg_payments.amount_usd", "stg_customers.country_code", "int_order_items_enriched.line_amount",
    "int_order_financials.sales_tax", "fct_orders.net_paid_usd", "fct_daily_revenue.revenue_marketing",
    "stg_products.list_price", "raw_refunds.refund_amt", "int_order_financials.order_date",
    "raw_payments.amt", "fct_orders.revenue_finance", "int_orders_enriched.order_status_group",
    "int_order_financials.order_total", "int_order_items_enriched.product_category",
    "dim_customers.order_count", "fct_orders.previous_order_date", "int_order_financials.net_paid_usd",
    "stg_orders.ship_date", "fct_payment_events.event_at",
)  # fmt: skip
# Other column ids named in the v0.2 question texts (dev-10's second column, dev-17's and dev-18's
# premises). Their text is kept verbatim, so these columns are forced into dev too.
V02_MENTIONS = (
    "dim_customers.lifetime_value", "int_customer_order_history.sales_tax", "stg_payments.amount_usd",
)  # fmt: skip
# Dev-pool supply the count table needs (questions-design.md §1), with room for spares.
NEED_TRACE = {"1": 10, "2-3": 13, "4-5": 13, "6+": 13}
NEED_DEEP_8 = 3  # trace targets at 8-10 hops
NEED_IMPACT = {"1": 6, "2-3": 6, "4-5": 5, "6+": 5, "indirect-only": 2}


def bucket(depth: int | None) -> str:
    if depth is None:
        return "n/a"
    if depth == 0:
        return "seed"
    return "1" if depth == 1 else "2-3" if depth <= 3 else "4-5" if depth <= 5 else "6+"


def frac(column: str) -> float:
    return int(hashlib.sha256((SALT + column).encode()).hexdigest()[:8], 16) / 2**32


def trap_columns(traps: Mapping[str, Any]) -> dict[str, set[str]]:
    """Columns each column-level trap names: its `columns`, the `to` end of its `edges`, and the
    first and last column of its `paths` (instances included). Exposures are model-level."""
    named: dict[str, set[str]] = defaultdict(set)
    for t in traps["traps"]:
        for part in [t, *(t.get("instances") or [])]:
            named[t["id"]] |= set(part.get("columns") or [])
            named[t["id"]] |= {e.split(" -> ")[1] for e in part.get("edges") or []}
            for p in part.get("paths") or []:
                named[t["id"]] |= {p[0], p[-1]}
    named.pop("exposures", None)
    named["doc_injection"] = {traps["doc_injection"]["column"]}
    return dict(named)


def build(spec: Mapping[str, Any], traps: Mapping[str, Any]) -> dict[str, Any]:
    v = gs.build_view(spec)
    depths: dict[str, int | None] = {**gs.compute_depths(v), **dict.fromkeys(v.seed_columns, 0)}
    named = trap_columns(traps)
    size = {t: len(cs) for t, cs in named.items()}
    strata: dict[tuple[str, str], list[str]] = defaultdict(list)
    for col in sorted(depths):
        hits = sorted((size[t], t) for t, cs in named.items() if col in cs)
        trap = hits[0][1] if hits else "none"
        small = trap != "none" and size[trap] <= SMALL_TRAP
        strata[("any" if small else bucket(depths[col]), trap)].append(col)
    forced = {c for c in (*V02_TARGETS, *V02_MENTIONS) if c in depths}
    columns: dict[str, dict[str, str]] = {}
    summary = []
    for (b, trap), cols in sorted(strata.items()):
        order = sorted(cols, key=lambda c: (c not in forced, frac(c), c))
        n, n_forced = len(cols), sum(c in forced for c in cols)
        if n == 1:
            quota = n_forced or int(frac(cols[0]) < SHARE)
        else:
            quota = max(n_forced, math.floor(SHARE * n + 0.5), 1)
        for i, c in enumerate(order):
            columns[c] = {"split": "dev" if i < quota else "test", "stratum": f"{b}|{trap}"}
        summary.append({"stratum": f"{b}|{trap}", "n": n, "dev": quota, "forced": n_forced})
    return {"salt": SALT, "share": SHARE, "strata": summary, "columns": columns}


def coverage(pools: Mapping[str, Any], spec: Mapping[str, Any]) -> list[str]:
    """Requirements the dev pool cannot meet (empty = OK)."""
    v = gs.build_view(spec)
    depths = gs.compute_depths(v)
    dev = {c for c, x in pools["columns"].items() if x["split"] == "dev"}
    short = []
    got = Counter(bucket(depths[c]) for c in dev if c in depths)
    short += [f"trace {b}: {got[b]} < {n}" for b, n in NEED_TRACE.items() if got[b] < n]
    deep8 = sum(1 for c in dev if (depths.get(c) or 0) >= 8)
    if deep8 < NEED_DEEP_8:
        short.append(f"trace 8-10 hops: {deep8} < {NEED_DEEP_8}")
    imp: Counter[str] = Counter()
    for c in dev:
        d = gs.downstream_depth(v, c)
        if d:
            imp[bucket(d)] += 1
        elif gs.downstream(v, c, include_indirect=True):
            imp["indirect-only"] += 1
    short += [f"impact {b}: {imp[b]} < {n}" for b, n in NEED_IMPACT.items() if imp[b] < n]
    missing = [c for c in (*V02_TARGETS, *V02_MENTIONS) if c in pools["columns"] and c not in dev]
    short += [f"forced dev target in test: {c}" for c in missing]
    return short


def render(pools: Mapping[str, Any]) -> str:
    head = (
        "# Column pools for the dev/test question splits (S09). GENERATED by\n"
        "# scripts/question_pools.py from lineage_spec.yml and traps.yml; do not edit by hand.\n"
        "# Column ids and splits only: no question text for either split.\n"
    )
    return head + yaml.safe_dump(dict(pools), sort_keys=False, width=100)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--check", action="store_true", help="exit 1 if pools.yml is stale")
    args = ap.parse_args()
    spec = yaml.safe_load(SPEC.read_text())
    pools = build(spec, yaml.safe_load(TRAPS.read_text()))
    short = coverage(pools, spec)
    if short:
        print("dev pool cannot supply the count table:\n  " + "\n  ".join(short))
        return 1
    text = render(pools)
    if args.check:
        stale = not OUT.is_file() or OUT.read_text() != text
        print("pools.yml is stale" if stale else "pools.yml is fresh")
        return int(stale)
    OUT.write_text(text)
    splits = Counter(x["split"] for x in pools["columns"].values())
    print(json.dumps({"columns": len(pools["columns"]), **splits, "strata": len(pools["strata"])}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
