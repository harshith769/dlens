# Explain: lineage engine (`src/dlens/lineage/`)

## What it does
`extract_lineage(ingest_result, project_dir)` turns ingest output (compiled SQL, sqlglot schema,
relation map) into:
- **DERIVES edges** (`Edge`): `from_column → to_column` with a kind (IDENTITY, RENAME,
  TRANSFORMATION, AGGREGATION), the SQL expression, a source-file citation and a confidence.
  Column ids use the spec §6 format `{unique_id}.{column}`, lowercased.
- **DEPENDS_ON** pairs, copied from the manifest so a model is never lost.
- A **parse report**: `ModelParse` per model with FULL / TABLE_ONLY / FAILED, the reason, the
  gaps, and `deferred_indirect` (window keys, kept for the parse report).
- **DEPENDS_ON_INDIRECT edges** (`IndirectEdge`, S03, ADR 0020): see `docs/explain/indirect-edges.md`.

`gold.compare` scores edges against a hand-written `lineage_spec.yml`, and
`scripts/compare_gold.py` runs the whole pipeline on a corpus.

## How it works
1. **DAG order** (`engine.topological_models`): `graphlib.TopologicalSorter` over manifest
   `depends_on`. The catalog already contains every built model, so order doesn't change the result
   today. It keeps the spec §7 contract ("later models can see earlier outputs") for when the schema
   is grown during the run.
2. **One sqlglot call per model**: `lineage(None, compiled_code, schema=..., dialect="duckdb")`
   returns `{output_column: Node}`. Each node's `expression` is the projection at that level, its
   `source` is the SELECT (or UNION) it lives in, and its `downstream` are the columns it reads.
   Leaves are `exp.Table` (a real table) or `exp.Placeholder` (sqlglot could not tell which table).
3. **Walk** (`engine._walk`): every root-to-leaf path is one candidate edge. Along the way:
   - A node whose `source` is a `Union` is *not* a step. Its expression is just the first branch's
     projection. Its children are the branches, and the branch index is carried down so each branch
     gets its own kind and citation.
   - Children read **only** inside a window's PARTITION BY / ORDER BY (`classify.window_key_columns`)
     are cut from the path and recorded in `ModelParse.deferred_indirect` as `WINDOW`.
     `lag(order_date) over (partition by customer_id order by order_date, order_id)` gives one
     edge (order_date) and two deferred keys (customer_id, order_id). order_date is both value and
     key, so it's a direct edge only.
4. **Leaf mapping**: a Table leaf's `db.schema.name` is normalised with the same
   `normalize_relation` that built the relation map, and looked up to get a dbt `unique_id`. Misses
   become gaps.
5. **Kind** (`classify.path_kind`): each step is either a bare column (pass-through) or an
   operation. An `AggFunc` that is not inside a `Window` is AGGREGATION. Anything else that isn't a
   bare column is TRANSFORMATION, including CASE, arithmetic, functions and windowed aggregates,
   which keep the row grain. The path's kind is the strongest step. A pure pass-through path is
   IDENTITY if the leaf name equals the output name, else RENAME. So
   `coalesce(agg.x, 0) <- sum(line_amount)` is AGGREGATION, and `a AS b` inside a CTE and then
   `b` outside is RENAME.
6. **Dedup**: one edge per `(from, to)`, keeping the strongest kind (and HIGH over LOW).
7. **Provenance** (`provenance.locate`): it scans the *source* `.sql` (Jinja and all) with a small
   depth-aware scanner. The scanner skips strings, comments and `{{ }}`/`{% %}`/`{# #}`, and splits
   every SELECT list into items with line ranges and output names (`as x`, or a bare `t.x`). The
   last item with the column's name is cited, because the final SELECT comes last. The k-th UNION
   branch gets the k-th match. Star-expanded columns cite the `*`. If nothing matches, the whole file
   is cited with `model_level_citation=True`.
8. **Ambiguous columns**: sqlglot returns a Placeholder leaf. The engine emits a LOW-confidence
   edge to every table in that SELECT's FROM/JOINs whose schema has the column, or that the schema
   doesn't know.
9. **Parse quality**: an exception from sqlglot → FAILED, with no column edges but DEPENDS_ON kept.
   Any gap (unmapped table, unexpanded `*`, an unresolvable column) → TABLE_ONLY, and the edges
   that did resolve are still emitted. Otherwise FULL.

## Why this design
- **`lineage(None, ...)` once per model** shares one qualified scope tree across all columns. It's
  cheaper and more consistent than one call per column. Golden test #0 pins this behaviour, since
  the `None` form is not the documented default.
- **Classify from the path, not just the outer SELECT.** dbt models compute in CTEs. Looking only at
  `coalesce(agg.items_subtotal, 0)` would call an aggregate a transformation.
- **Window keys are filtered by us.** sqlglot treats every column inside the projection as an input,
  including PARTITION BY / ORDER BY. DESIGN.md says those are indirect dependencies. They're
  recorded rather than dropped so v0.3 doesn't need to re-derive them.
- **CASE conditions stay direct.** The gold spec counts `unit_price < list_price` as feeding
  `is_discounted`. The condition decides the value, unlike a join key.
- **Cite the source file.** Users and the validator open the source `.sql`, and compiled line numbers
  drift whenever Jinja expands to several lines.
- **Recompiled SQL.** `build --empty` compiles refs as `(select * from x where false limit 0)`.
  Ingest now lets `docs generate` recompile, so no fake `SELECT *` hop appears (see ingest.md).
- **`short_id` only for gold comparison.** The short form collides across packages and sources, so
  it never becomes an identifier inside the graph.

## Alternatives rejected
- **Per-column `lineage(col, sql)` calls**: N parses per model for the same answer.
- **Walking the qualified AST by hand for direct edges**: re-implements sqlglot's scope resolution
  (CTEs, subqueries, star expansion, UNION). We walk the AST ourselves only for the small things
  sqlglot doesn't model: window-key filtering and aggregate-vs-window detection.
- **Classifying from the outermost projection only**: misclassifies CTE aggregates (above).
- **Citing compiled SQL via sqlglot token positions**: exact, but points at a file users don't edit.
- **Parsing the source with sqlglot after stripping Jinja**: fragile with loops and macros. The
  scanner only needs item boundaries and names, and falls back honestly.
- **Unwrapping the `--empty` subqueries in the AST**: works, but keeps a dbt quirk inside the
  engine. Recompiling removes it at the source.
- **Dropping ambiguous columns**: silent recall loss. LOW-confidence edges keep them visible.

## Construct support
Generated from `tests/golden/fixtures/` by `scripts/gen_support_matrix.py` (a test fails if it is
stale). Every row is a golden fixture whose expected edges were written by reasoning from the SQL
and the strongest-kind rule before the engine ran. `partial` means the direct edges are right but
a non-value dependency (join / group / filter / window key) is not an edge yet.
`no (untested)` rows have no fixture at all: they are known gaps listed in `UNTESTED` in
`tests/golden/_harness.py`, so nobody reads silence as support.

<!-- support-matrix:start -->
| Construct | Supported | Note |
|---|---|---|
| `alias_rename` | yes |  |
| `cast_and_coloncolon` | yes | a cast is an operation, not a bare column, so TRANSFORMATION even when the type is unchanged |
| `cte_chain_3` | yes |  |
| `distinct` | yes |  |
| `group_by_having` | yes | GROUP BY user_id targets every column but user_id (direct wins); HAVING tax is FILTER to all; count(*) reads no column, so it is recorded like a constant |
| `indirect_agg_filter_vs_case` | yes | same logic, two classes: FILTER (WHERE) is CONDITIONAL; the CASE condition is a direct AGGREGATION input |
| `indirect_group_by_all` | yes | GROUP BY ALL groups by the non-aggregate projections' columns |
| `indirect_group_by_cte` | yes | GROUP BY inside a CTE targets only the columns computed through it (n_orders), not c.id / c.name |
| `indirect_in_subquery` | yes | the outer column, the subquery's selected column and its WHERE column are all FILTER (the outer WHERE decides) |
| `indirect_join_final` | yes | every column in ON (equi and non-equi) is a JOIN key to every output column of the final SELECT |
| `indirect_join_key_via_cte` | yes | the JOIN key paid.order_id is resolved through the CTE to payments.order_id; the CTE's GROUP BY targets only paid_amt |
| `indirect_join_using` | yes | a USING column is a JOIN key on both sides |
| `indirect_order_by_limit` | yes | top-level ORDER BY (with LIMIT) is SORT to every column; amt -> amt stays direct only |
| `indirect_order_by_no_limit` | yes | top-level ORDER BY without LIMIT is still SORT to every column |
| `indirect_positional_group_order` | yes | GROUP BY 1, 2 and ORDER BY 1 resolve to the columns of those projections |
| `indirect_string_agg_order` | yes | ORDER BY inside an aggregate is SORT to that column only |
| `indirect_union_branch_where` | yes | a WHERE in one branch of a top-level UNION is FILTER to every output column |
| `indirect_where` | yes | WHERE columns are FILTER to every output; amt -> amt stays direct only |
| `indirect_where_exists` | yes | every column in the correlated EXISTS subquery is FILTER (the outer WHERE decides); c.id -> m.id stays direct only |
| `indirect_window_lag_suppressed` | yes | amt is the lag argument and the ORDER BY key: direct only (suppressed); user_id is WINDOW |
| `join_aliases` | yes | join keys o.user_id / c.id are JOIN edges to every output column, never direct |
| `kind_scalar_subquery_sibling` | no | S04: a scalar subquery's aggregate leaks its kind to a sibling column |
| `kind_window_over_grouped_agg` | no | S04: sum(sum(x)) OVER (...) - the inner grouped aggregate is classified as windowed |
| `literal_column` | yes | constants have no edges and are recorded in ModelParse.constants, not gaps |
| `nested_case` | yes | CASE conditions are direct (they decide the value) |
| `qualify_row_number` | yes | QUALIFY keys are FILTER, also inside its OVER (the clause decides first); user_id -> user_id stays direct only |
| `scalar_subquery_select` | yes | correlation keys c.id and o.user_id select rows in the subquery: FILTER to cust_name only, no direct edge |
| `self_join` | yes | both ON columns are JOIN keys; employees.id -> m.id stays direct only |
| `star_exclude_replace` | yes | price is excluded: no output column, no edge |
| `star_join` | yes | tables share no column names; ON keys are JOIN to every column except their own pass-through |
| `subquery_from` | yes | GROUP BY inside the derived table targets only total_plus (user_id is direct) |
| `union_all_3` | yes | each branch has its own kind: the UNION node is not a step |
| `union_distinct` | yes | UNION vs UNION ALL changes no edge |
| `window_sum_partition` | yes | windowed aggregate keeps the row grain; PARTITION BY / ORDER BY keys are WINDOW to running_amt |
| star join with duplicate column names | no (untested) | `SELECT *` over a join whose sides share a column name; no fixture, so the output columns and their edges are not guaranteed |
<!-- support-matrix:end -->

**Constants are not gaps.** An output column that reads no input column (`'usd' AS currency`,
`current_timestamp`, `1 + 1`, `count(*)`) gets no edges and is recorded in `ModelParse.constants`
(lowercased output names). The model stays FULL when that is its only oddity: real projects have
many such columns and they are fully understood, not unresolved. Gaps (TABLE_ONLY) are reserved for
things the engine could not resolve. Consequently "every non-seed model column has an upstream" holds
only for non-constant columns; the property test excludes recorded constants. A column that is a
constant in only some UNION branches still has edges and is not recorded.

## Explain-back questions
1. In `int_payment_events`, why would the refund branch's `event_amount_usd` edge be RENAME
   instead of TRANSFORMATION if the UNION node were treated as a step? Where in `_walk` is that
   prevented?
2. `dim_customers.lifetime_value` is `coalesce(order_agg.lifetime_value, 0)`. Walk through the
   steps `path_kind` sees for `fct_orders.sales_tax → dim_customers.lifetime_value`, and explain
   why the result is AGGREGATION. What would change if the CTE used `sum(...) over (partition by
   customer_id)` instead of `group by`?
3. A model's parse report says TABLE_ONLY with gap `x <- table db.main.y is not a dbt node`. What
   edges does the graph still have for that model, and name two causes that would produce this gap.
