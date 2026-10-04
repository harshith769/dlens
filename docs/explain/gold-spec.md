# Explain: the gold spec format, the D7 expansion and the spec checker

Files: `src/dlens/gold_spec.py` (D7 expansion), `scripts/check_gold_spec.py` (checker),
`corpora/synthetic_shop/lineage_spec_v2.yml` (v2 gold), `corpora/synthetic_shop/spec_v2_expected.yml`
(the design's numbers), `corpora/synthetic_shop/traps_v2.yml` (v2 traps).

## What it does
The gold lineage spec is the answer key for the lineage engine and for every benchmark question.
It is written by hand from the corpus design (`DESIGN_v2.md`), never from parser output. The
checker makes sure the spec is internally consistent and that it reproduces the numbers the design
states, before any SQL exists. If the spec and the design disagree, one of them has a typo; the
checker finds it without running dlens or dbt.

```
uv run python scripts/check_gold_spec.py                       # v1 spec: structure only
uv run python scripts/check_gold_spec.py --spec corpora/synthetic_shop/lineage_spec_v2.yml \
    --expected corpora/synthetic_shop/spec_v2_expected.yml     # v2: every check
```

## How it works

### Spec format (v2)
```yaml
seeds:   {raw_orders: [id, user_id, ...], ...}                       # column inventory
models:  {int_order_profit: {depends_on: [...], columns: [...]}, ...} # DESIGN_v2 §2 "Upstream"
edges:   [{from, to, kind, phase: v0.1, traps}]                       # direct; same rows as v1
indirect_edges:
  - {from: stg_products.product_id, model: int_order_items_enriched, type: JOIN,
     phase: v0.3, targets: all, traps: [join_key_only]}
  - {from: int_order_item_margins.order_id, model: int_order_profit, type: GROUP_BY, phase: v0.3,
     targets: [cogs_total, gross_margin, contribution_margin, is_profitable], via: item_margins}
```
- The **inventory** (`seeds`, `models`) is written from the design's tables, independently of the
  edges. Without it, "every column has an incoming edge" would be true by construction, because
  the columns would be read off the edges.
- **Indirect rows** are compact: one row per key column and clause. `targets: all` means the
  clause sits in the model's final SELECT; an explicit list names the columns computed in or
  through the CTE, derived table or function the clause belongs to. `via` names that CTE or
  derived table (or `subquery`) whenever the targets are a list or the key reaches the model
  through one.
- Indirect edges live under their own key, so code that reads `edges` (integration tests,
  `compare_gold.py`) keeps seeing direct edges only.

### The D7 expansion (`dlens.gold_spec.expand_indirect`)
DESIGN_v2 §10 D7 turns rows into `(from, to, type)` pairs:
- `targets: all` → every column of the model, **minus columns that already have a direct edge from
  the same `from`** ("no double counting": only the direct edge is kept). Those dropped pairs are
  returned as `suppressed`.
- an explicit list → exactly those columns. A listed column that already has a direct edge is a
  `conflict`: the author wrote something D7 forbids, and the checker fails.
- One `(from, to)` pair may carry several indirect types (JOIN and GROUP_BY, say). A duplicate is
  the same `(from, to, type)`. How metrics count such pairs is decided in S10.

It is one function, in the package (not under `src/dlens/lineage/`), so the checker, the tests
and S03's engine-vs-gold comparison all use the same rule.

### Checks
Structural (always): schema; endpoints exist in the inventory; no duplicate direct `(from, to)` or
indirect `(from, to, type)`; no explicit indirect target that is also direct; every edge's source
model is in the target model's `depends_on`, and every `depends_on` parent contributes at least one
edge, direct or indirect (`int_orders_enriched` feeds `fct_product_performance` only through a JOIN
key and a FILTER); every model column has an incoming edge (D3).

With `--expected`: counts per layer and kind (§0, §2); depth recomputed from **direct edges only**
against the §5 histogram, the n/a set and every Appendix B row (column, hops, and each path step is
a real direct edge); 6+ columns per model; max depth; columns the design says must not exist (§1:
`stg_orders.ship_date` for dev-19); unreachable pairs, both direct-only and direct + indirect
(dev-10: `raw_payments.amt` never reaches `dim_customers.lifetime_value`); the v1 direct edges are
content-identical to `lineage_spec.yml` (from, to, kind, phase, compared as a multiset over the v1
models); every model, column, edge, path and indirect row named in the traps file exists.

Reported, never gated: indirect rows, pairs and models per type, split v1 vs new models; how many
pairs D7 suppressed; mismatches between edge `traps:` tags and the traps file (the traps file is
the source of truth for question stratification; tags are informational).

Depth: longest direct-edge path from a seed column (`docs/explain/eval-dev.md`). A column with no
direct path to a seed has depth n/a; in v2 that is only `int_web_sessions_clean.session_number`
(`row_number()` with no argument).

## Why this design
- **Gold before SQL.** The spec is checked against the design's own counts while no SQL exists,
  so nothing the parser does can leak into it.
- **Numbers in one file.** `spec_v2_expected.yml` holds every expected number with the design
  section it comes from, so a reviewer checks one file against one document.
- **Compact indirect rows.** 120 rows instead of 621 pairs (63 more pairs are suppressed by D7).
  A reviewer reads one row per clause, the way the SQL is written, and D7 does the fan-out the
  same way every time.

## Alternatives rejected
- **Indirect pairs written out one by one.** Too long to review, and D7's "minus direct" rule would
  be applied by hand hundreds of times.
- **`targets: all` keeping pairs that also have a direct edge, de-duplicated later by consumers.**
  Every consumer would need to remember the rule; one function is safer.
- **Inferring columns from edge endpoints** (as the v1 spec does). Makes D3 untestable and
  `targets: all` circular.
- **Comparing the v1 edges with a git tag.** CI clones may lack tags; the v1 file sits in the same
  directory until S02b swaps the files.

## Decisions recorded (S02a plan review)
- `int_customer_order_history`: `order_date` is both the `lag` argument and a window ORDER BY key.
  D7 keeps only the direct edge, so the gold has WINDOW edges from `customer_id` and `order_id`
  only. This differs from `DESIGN.md`'s "Deferred indirect edges" table, which lists all three
  window keys; that table predates D7.
- `int_order_promotions`: the outer `stg_order_promotions.promotion_id`, the subquery's
  `stg_promotions.promotion_id` and `promo_channel` are all FILTER (D1: columns in an
  `IN (subquery)` predicate).
- `fct_product_performance` GROUP BY: `int_order_item_margins.product_id`,
  `stg_products.product_name`, `stg_products.category`.
- `fct_monthly_finance`: each derived table's GROUP BY key targets only that table's columns
  (`revenue_monthly`, `margins_monthly`, `adjustments_monthly`); the outer month join keys target
  every column; the `lag` ORDER BY month is a WINDOW edge to `revenue_finance_mom_change` only.
  `fct_marketing_attribution`: the `attributed_daily` GROUP BY keys target the four columns
  computed through it; every join key targets every column.
- **CTE and derived-table names are part of the gold.** `via` names CTEs that do not exist yet:
  `item_margins` (`int_order_profit`), `rfm_base` (`dim_customer_rfm`: the join lives there and
  the score CTEs sit on top), `attributed_daily` (`fct_marketing_attribution`),
  `latest_snapshots` (`fct_inventory_status`: the QUALIFY runs before the join),
  `revenue_monthly` / `margins_monthly` / `adjustments_monthly` (`fct_monthly_finance`). S02b
  writes the SQL with these names and this structure. The v1 names (`item_agg`,
  `refunds_per_order`, `cash_per_order`, `order_agg`) come from the frozen SQL.
- Rows for clauses attached to a function in the final SELECT (CONDITIONAL, a SELECT-list
  WINDOW, SORT inside `string_agg`) have an explicit target list but no `via`: there is no CTE or
  derived table to name.

## Explain-back questions
1. `stg_a.k` is a JOIN key in model `m`'s final SELECT, and `m.k` is `stg_a.k` unchanged. Which
   pairs does the row `{from: stg_a.k, model: m, type: JOIN, targets: all}` produce, and why is
   `stg_a.k -> m.k` not among them?
2. Why does the spec carry a column inventory (`models.columns`) when every column already appears
   as an edge endpoint, and which check would become meaningless without it?
3. `int_web_sessions_clean.session_number` has depth n/a but passes D3. Explain both facts, and
   say why it changes none of the 55 columns at 6+ hops.
