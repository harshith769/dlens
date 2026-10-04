# Explain: indirect edges (`DEPENDS_ON_INDIRECT`, ADR 0020)

Files: `src/dlens/lineage/engine.py` (`_indirect`, `_resolve_key`, `_clause_text`,
`_model_indirect`), `src/dlens/lineage/classify.py` (`clause_position`, `function_key`,
`key_columns`), `src/dlens/lineage/models.py` (`IndirectEdge`, `IndirectKind`),
`src/dlens/lineage/gold.py` (`compare_indirect`), `src/dlens/graph/graph.py` (format v3).

## What it does
For every model, the engine emits indirect edges: a column that decides which rows reach an
output column (JOIN, FILTER), how they are grouped (GROUP_BY), ordered (SORT, WINDOW) or which
rows an aggregate counts (CONDITIONAL), without flowing into the value. They live in
`LineageResult.indirect` and `LineageGraph.indirect_edges()`, separate from direct edges. Nothing
user-facing reads them yet: trace, impact, tools, validator, CLI and demo are unchanged.

## How it works
1. **One qualified AST.** `qualified_scope` qualifies the compiled SQL once and builds the scope
   tree. `lineage(None, ..., scope=..., trim_selects=False)` uses the same tree, because trimming
   would re-parent projections onto copies.
2. **Targets from the lineage trees.** For each output column, every node on its tree records its
   SELECT (`by_select`) and its projection (`by_projection`). A row-set clause in SELECT S targets
   every output whose tree passes through S. In the final SELECT that is every output, constants
   included. A function-attached clause targets the outputs through its projection.
3. **Walk the scopes** (final SELECT, CTEs, derived tables, UNION branches, subqueries). For each
   column in a scope, `clause_position` finds its top-level clause:
   - The clause decides first: ON → JOIN; WHERE, HAVING and QUALIFY → FILTER; GROUP BY → GROUP_BY;
     ORDER BY → SORT.
   - In the SELECT list, the innermost function key decides: window → WINDOW, aggregate
     `FILTER (WHERE)` → CONDITIONAL, aggregate ORDER BY → SORT.
   - Function arguments and CASE conditions give nothing (they are direct).
   - A subquery inside a clause (IN, EXISTS, a comparison) passes the clause's type and targets
     to every column in it.
   - `GROUP BY ALL` uses the columns of the non-aggregate projections. USING and positional
     GROUP BY are expanded by `qualify`.
4. **Resolve each key** like a direct leaf:
   - A table → its dbt column (HIGH confidence).
   - A CTE or derived table → `to_node` plus `_walk`/`_resolve_leaf`, through the projection.
   - A correlated column → the parent scopes.
   - A bare select alias (`ORDER BY 1`, `ORDER BY alias`) → that projection.
   - Ambiguous and unqualified → LOW confidence, one edge to each candidate table.
5. **D7 suppression and dedup.** A (from, to) pair that has a direct edge is dropped. The rest is
   one edge per (from, to, type), HIGH preferred over LOW.
6. **Provenance.**
   - `expression` is the clause, cut verbatim from the compiled SQL with whitespace collapsed.
     The cut uses the token positions sqlglot keeps on identifiers and literals: the clause
     keyword before the first token, then a scan to the clause's end at paren depth 0.
   - When those positions are missing or point elsewhere (positional GROUP BY copies the
     projection's tokens), `expression` falls back to the qualified SQL.
   - `key` is the column as written in the clause.
   - Citations are **model-level** (the whole source file). This deviates from spec §6 until a
     clause locator ships with the exposure of indirect edges. `engine_gaps.yml` tracks it
     (`indirect_edges`, target S04).
7. **Direct walk fix.** Columns used only in an aggregate's FILTER (WHERE) or ORDER BY are no
   longer direct inputs (`key_columns`). Only window keys still feed `deferred_indirect`, which
   is kept unchanged for the parse report until exposure.
8. **Graph format v3** adds `indirect`. `load` reads v2 and v3, so the committed demo `graph.json`
   (v2) loads with no indirect edges. A v2 cache is rebuilt.

## Why this design
- **Same resolution as direct edges.** Keys through CTEs land on the same upstream columns as
  direct edges, so suppression compares like with like.
- **Targets come from the lineage trees, not from the SQL layout.** "Computed in or through" is
  exactly "the SELECT is on the column's tree".
- **Kept outside the nx graph.** Hop depth and every traversal stay direct-only by construction.
  Exposure is a later, metrics-driven decision.

## Alternatives rejected
- **Keys taken from sqlglot's lineage children only.** They never include WHERE, ON or GROUP BY
  columns.
- **OpenLineage CONDITIONAL for CASE conditions.** It contradicts the frozen v1 gold.
- **Innermost clause wins** (a QUALIFY window key would be WINDOW). QUALIFY removes rows.
- **CTE clauses target every output.** That over-states impact (the derived tables in
  `fct_monthly_finance`).
- **A clause locator in S03.** No consumer reads the citations yet. Recorded as an S04 gap
  instead.

## Results (S03)
- synthetic_shop: 621/621 gold (from, to, type) triples matched. P = R = F1 = 1.000 per type and
  per model, 0 LOW-confidence edges.
- Caveat: one AI wrote both the gold and the engine from the same rules. The perturbation oracle
  (S05) is the independent check.

## Explain-back questions
1. In `int_order_promotions`, why are `stg_promotions.promo_channel` (in the subquery's WHERE)
   and `stg_promotions.promotion_id` (the subquery's SELECT list) both FILTER edges to every
   column, while `discount_pct` is only a SORT edge to `promo_codes`?
2. `fct_monthly_finance`: the GROUP BY of the `revenue_monthly` derived table targets four
   columns, not `net_revenue`. Which data structure in `_indirect` decides that, and why is
   `finance_month` not a target even though it passes through `revenue_monthly`?
3. `count(x) FILTER (WHERE c)` and `sum(CASE WHEN c THEN 1 END)` encode the same logic. What
   edge does `c` get in each case, and which two places in the code make that happen?
4. Why does the engine pass `trim_selects=False` to sqlglot, and what broke without it?
5. A v0.2 `graph.json` and a v0.2 `target/dlens_graph.json` are both read by the v3 code. Why is
   one loaded and the other rebuilt?
