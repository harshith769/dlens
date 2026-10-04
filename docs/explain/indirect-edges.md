# Explain: indirect edges (`DEPENDS_ON_INDIRECT`, ADR 0020)

Files: `src/dlens/lineage/engine.py` (`_indirect`, `_resolve_key`, `_clause_text`,
`_keyword_span`, `_written_key`, `_model_indirect`), `src/dlens/lineage/classify.py`
(`clause_position`, `function_key`, `key_columns`), `src/dlens/lineage/provenance.py`
(`line_map`, `locate_clause`), `src/dlens/lineage/models.py` (`IndirectEdge`, `IndirectKind`,
`ModelParse.citation_gaps`), `src/dlens/lineage/gold.py` (`compare_indirect`),
`src/dlens/graph/graph.py` (format v4, `include_indirect` traversal), `src/dlens/cli.py`
(`--include-indirect`).

## What it does
For every model, the engine emits indirect edges: a column that decides which rows reach an
output column (JOIN, FILTER), how they are grouped (GROUP_BY), ordered (SORT, WINDOW) or which
rows an aggregate counts (CONDITIONAL), without flowing into the value. They live in
`LineageResult.indirect` and `LineageGraph.indirect_edges()`, separate from direct edges. Each one
cites its clause's lines in the model's source file (S04). They are exposed **opt-in** only:
`upstream`/`downstream(include_indirect=True)` and `dlens trace|impact --include-indirect`
(graph.md). The agent tools, validator, UI and demo stay direct-only until S10/S12 decide how
answers use them.

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
   - `key` is the column as written in the clause, in qualified form (`orders.user_id`, an alias
     like `lv`, a CTE column like `s.cust_id`). For a positional GROUP BY / ORDER BY item it is
     the position as written (`"1"`, read back by `_written_key` from the clause text, because
     qualify replaces positions). For GROUP BY ALL it is `"ALL"`.
4. **Resolve each key** like a direct leaf:
   - A table → its dbt column (HIGH confidence).
   - A CTE or derived table → `to_node` plus `_walk`/`_resolve_leaf`, through the projection.
   - A correlated column → the parent scopes.
   - A bare select alias (`ORDER BY 1`, `ORDER BY alias`) → that projection.
   - Ambiguous and unqualified → LOW confidence, one edge to each candidate table.
5. **D7 suppression and dedup.** A (from, to) pair that has a direct edge is dropped. The rest is
   one edge per (from, to, type), HIGH preferred over LOW.
6. **Clause text and span** (`_clause_text`).
   - `expression` is the clause, cut verbatim from the compiled SQL with whitespace collapsed.
     The cut uses the token positions sqlglot keeps on identifiers and literals: the clause
     keyword before the first token, then a scan to the clause's end at paren depth 0
     (`_clause_end`). The same cut gives the clause's **span** (character offsets) in the compiled
     SQL.
   - When those positions are missing or point elsewhere (USING expanded by qualify, positional
     GROUP BY copying the projection's tokens), `expression` falls back to the qualified SQL, and
     `_keyword_span` finds the span by scanning the owning SELECT at its own paren depth for the
     keyword. GROUP BY / ORDER BY take the first match. A JOIN takes the k-th ON/USING, where k
     counts the joins that have a condition.
7. **Clause citation** (`provenance.line_map`, `locate_clause`; S04).
   - dbt renders Jinja in place, so compiled and source lines align except where Jinja expands.
     `line_map` aligns them with `difflib` on stripped lines. Equal runs, and changed runs of
     equal length (a rendered `{{ ref() }}`), map line to line. A changed run of a different
     length (a `{% for %}` loop) maps to the whole source run. Inserted compiled lines map to
     nothing.
   - `locate_clause` maps the span's first and last compiled lines to source lines. It then
     **checks** that those lines hold the key as written (its last segment, a position or `ALL`).
     A clause that a macro writes (`{{ only_big_orders() }}`) maps to the macro's line but fails
     the check.
   - A located edge cites `lines` in the same file and numbering as direct edges, with
     `model_level_citation=False`. Otherwise the edge cites the whole file, and
     `ModelParse.citation_gaps` records `"<TYPE> <clause>: <reason>"`. `dlens report` prints it.
8. **Direct walk.** Columns used only in a function-attached key position (window keys, an
   aggregate's FILTER (WHERE) or ORDER BY) are not direct inputs (`key_columns`). The v0.1
   `ModelParse.deferred_indirect` list of window keys is retired in S04. It equalled the
   distinct WINDOW (from, to) pairs on every golden, on synthetic_shop (14) and on jaffle (0).
   `dlens report` keeps its "Deferred indirect (window keys)" line, counted from WINDOW edges.
9. **Graph format.** v3 added `indirect`. v4 (S04) adds `citation_gaps` and drops
   `deferred_indirect`. `load` reads v2–v4, so the committed demo `graph.json` (v2) loads with no
   indirect edges. An older cache is rebuilt.

## Why this design
- **Same resolution as direct edges.** Keys through CTEs land on the same upstream columns as
  direct edges, so suppression compares like with like.
- **Targets come from the lineage trees, not from the SQL layout.** "Computed in or through" is
  exactly "the SELECT is on the column's tree".
- **Kept outside the nx graph.** The default traversals stay direct-only by construction, and
  `include_indirect` merges the indirect index in only when asked. Exposure in answers is a later,
  metrics-driven decision (S10/S12).
- **Cite through the compiled SQL, then map lines back.** The engine already knows exactly where
  each clause is in the compiled SQL (it cut the text from there). Mapping those lines back to the
  source is a small, general step that handles every clause type at once, and it shares the
  direct edges' rule (cite the source file the user opens).
- **Check the key, don't trust the mapping.** A line map can land on a Jinja line that produced
  the clause without spelling it. The key check turns that into an honest model-level citation
  with a reason, never a wrong line.

## Alternatives rejected
- **Keys taken from sqlglot's lineage children only.** They never include WHERE, ON or GROUP BY
  columns.
- **OpenLineage CONDITIONAL for CASE conditions.** It contradicts the frozen v1 gold.
- **Innermost clause wins** (a QUALIFY window key would be WINDOW). QUALIFY removes rows.
- **CTE clauses target every output.** That over-states impact (the derived tables in
  `fct_monthly_finance`).
- **A clause locator in S03.** No consumer read the citations yet. It was recorded as a gap
  and shipped in S04 with the opt-in exposure.
- **A second scanner over the source SQL to find clauses** (like `select_items` for projections).
  It would need its own rules for every clause type and for which of several WHERE clauses an
  edge belongs to. The compiled span already answers both.
- **Citing compiled SQL lines.** Exact, but users and the validator open the source file, and
  compiled lines drift wherever Jinja expands.
- **A reason field on every `IndirectEdge`.** Most edges would carry `null`. One list per model in
  the parse report is where `dlens report` already shows what could not be resolved.

## Results
- S03: synthetic_shop, 621/621 gold (from, to, type) triples matched. P = R = F1 = 1.000 per
  type and per model, 0 LOW-confidence edges.
- S04 gate: indirect-edge F1 ≥ 0.90 is a hard assertion (`test_indirect_edge_gate`;
  `compare_gold.py --indirect` exits 1 below it). It measures 1.000.
- S04 citations: all 621 indirect edges on synthetic_shop and all 41 on jaffle cite their clause
  (0 model-level), and every cited range holds its key. The rule test runs over every golden
  fixture too. `engine_gaps.yml` has no entries left.
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
4. `select user_id, sum(amt) as total from orders group by 1` gives a GROUP_BY edge with key
   `"1"`. Why can't the key and the clause span come from sqlglot's tokens here, which two
   functions recover them, and what does the citation check look for in the cited lines?
5. A model's WHERE clause is written by a macro, `{{ only_big_orders() }}`, which compiles to
   `where amt > 100` on the same line. What do `line_map` and `locate_clause` return for that
   edge, what does the edge cite, and where does the reason end up?
6. `jaffle_shop/orders.sql` builds columns with a `{% for %}` loop, so the compiled file has
   more lines than the source. Why do its WHERE/GROUP BY clauses still get exact source lines,
   and what would happen to a clause inside the loop?
