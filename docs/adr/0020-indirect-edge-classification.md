# 0020. Indirect-edge classification and targets

- Status: Accepted
- Date: 2026-10-04
- Source: docs/DLENS_SPEC.md, Section 0, row 31; corpora/synthetic_shop/DESIGN_v2.md §4, §10 D1 and D7
- Implemented in: S03 (v0.3, A3 part 1)

## Context

Spec §6 defines `DEPENDS_ON_INDIRECT` edges (JOIN, FILTER, GROUP_BY, WINDOW, SORT, CONDITIONAL):
a column that decides which rows exist, how they are grouped or ordered, without flowing into a
value. DESIGN_v2 D1 (classification) and D7 (targets) were working rules for the S02 gold spec.
The engine now emits these edges, so the rules have to be fixed in one place that both the gold
and the engine follow.

## Decision

**Classification: the clause decides first.** For a column occurrence in a SELECT `S`:

| Where the column is | Type |
|---|---|
| `JOIN … ON` / `JOIN … USING` | JOIN |
| `WHERE`, `HAVING`, `QUALIFY` (also inside an `OVER (…)` within `QUALIFY`) | FILTER |
| `GROUP BY` (expressions, positions and `ALL` resolve to the projection's columns) | GROUP_BY |
| `ORDER BY` of the SELECT | SORT |
| SELECT list, window `PARTITION BY` / `ORDER BY` | WINDOW |
| SELECT list, aggregate `FILTER (WHERE …)` | CONDITIONAL |
| SELECT list, `ORDER BY` inside an aggregate (`string_agg(x, ',' ORDER BY y)`) | SORT |
| SELECT list, function argument, CASE condition | direct (no indirect edge) |

- The outermost clause of `S` wins: a window key inside `QUALIFY` is FILTER, not WINDOW.
- In the SELECT list, function arguments are direct. The innermost function-attached key
  position decides: `count(*) FILTER (WHERE c) OVER (PARTITION BY k)` gives `c` CONDITIONAL and
  `k` WINDOW.
- **Subqueries in a clause** (`IN (SELECT …)`, `EXISTS (…)`, a scalar comparison in `WHERE` or
  `ON`): every column anywhere inside the subquery takes the clause's type and targets. In
  `WHERE a IN (SELECT b FROM u WHERE z <> 1)`, `a`, `b` and `z` are all FILTER.
- **Scalar subqueries in the SELECT list** are their own scope, and their clauses are classified
  as above. The correlation keys of such a subquery (`(SELECT max(c.name) FROM c WHERE
  c.id = o.user_id) AS cust_name`) are FILTER edges to that subquery's output column only:
  the subquery is the scope in which those keys select rows.

**Targets (D7).**
- Row-set clauses (`JOIN`, `WHERE`, `HAVING`, `QUALIFY`, `GROUP BY`, the SELECT's `ORDER BY`):
  an edge from each key column to every output column computed in or through that SELECT, CTE or
  derived table. "Through" means the SELECT is on the output column's lineage tree. In the
  model's final SELECT, or in any branch of a top-level UNION, that is every output column,
  including constants.
- Function-attached clauses (`OVER`, aggregate `FILTER (WHERE)`, aggregate `ORDER BY`): only the
  output columns computed through the projection that contains the function.
- No double counting: if `(from, to)` already has a direct edge, only the direct edge is kept.
  One `(from, to)` pair may carry several indirect types (JOIN and GROUP_BY, say). Each type is
  its own edge.
- Key columns are resolved to upstream model columns by the same resolution as direct edges.
  A key that arrives through a CTE or derived table is followed through its projection to the
  upstream column, and an ambiguous unqualified key gets LOW confidence.
- Indirect edges never count toward hop depth.

**Provenance.** Indirect edges carry the clause SQL verbatim from the compiled SQL in
`expression`. They carry a model-level citation (the whole source file,
`model_level_citation=True`) until a clause locator ships with their exposure. This deviates
from spec §6 ("same provenance"), and `engine_gaps.yml` tracks it (target S04).

## Consequences

- **Deviation from OpenLineage.** OpenLineage's CONDITIONAL covers CASE conditions. Here CASE
  conditions stay direct, because they decide the value (v1 gold: `is_discounted`,
  `order_status_group`). CONDITIONAL is only an aggregate's `FILTER (WHERE …)`.
- **FILTER-vs-CASE asymmetry, on purpose.** `count(x) FILTER (WHERE c)` gives `c` a CONDITIONAL
  edge. `sum(CASE WHEN c THEN 1 ELSE 0 END)` gives `c` a direct AGGREGATION edge. The corpus pairs
  `int_order_shipping.late_shipment_count` with `fct_shipping_performance.late_shipment_count`,
  so goldens and the perturbation oracle show the difference.
- The direct-edge walk must also drop columns used only in an aggregate's `FILTER (WHERE)` or
  `ORDER BY` (they were AGGREGATION inputs before).
- A CTE that contributes no output column gets no targets from its own clauses, as the D7
  wording says. The clause that joins or filters on it in the outer SELECT still produces edges.
- Trace, impact, the tools, the validator, the CLI and the demo ignore indirect edges until the
  metrics design decides how they are scored and shown.

## Alternatives rejected

- **OpenLineage's classification (CASE conditions are CONDITIONAL).** It would contradict the
  frozen v1 gold, where CASE conditions are direct edges.
- **Innermost clause wins** (a window key inside `QUALIFY` is WINDOW). `QUALIFY` removes rows. The
  window only computes the value the filter compares.
- **Row-set clauses in a CTE target every output column.** That over-states impact. A GROUP BY
  inside one derived table of `fct_monthly_finance` does not shape the columns from the other
  two.
- **Keys from sqlglot's lineage children only.** sqlglot lists the columns of a projection, so it
  never sees `WHERE`, `JOIN ON` or `GROUP BY` columns.
- **Counting indirect edges in hop depth.** Depth measures how values flow. A join key does not
  flow into a value.

## Clarification (S04)

- **"Hop depth" means the gold/question depth metric.** "Indirect edges never count toward hop
  depth" (Targets) is about the depth used to grade questions and to report multi-hop
  difficulty, which counts direct edges only. It does not limit traversal. When
  `upstream`/`downstream` run with `include_indirect=True` (opt-in since S04), their `max_depth`
  counts every hop, direct or indirect.
- **Provenance.** The model-level citation above was an interim state. Since S04, indirect edges
  cite their clause's lines in the model's source file (the same file and numbering as direct
  edges): `lineage/provenance.py`, `line_map` and `locate_clause`. A clause that can't be located
  falls back to the whole file, and its reason is recorded in `ModelParse.citation_gaps`. For a
  positional GROUP BY / ORDER BY item, `key` is the position as written (`"1"`), and for GROUP BY
  ALL it is `"ALL"`.
- **Exposure.** Trace and impact follow indirect edges only on request (`--include-indirect`).
  The tools, validator, UI and demo stay direct-only until S10/S12 (see `docs/explain/graph.md`).
