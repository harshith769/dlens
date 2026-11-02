# 0030. Deterministic tie-break between equal-strength paths (S15e)

- Status: Proposed (awaiting owner approval at the S15e STOP)
- Date: 2026-11-02
- Amends: `src/dlens/lineage/engine.py` `_model_edges` (named by the S15e plan); no public
  interface change (spec §7 stable); graph format unchanged; artifact `BUILDER_VERSION` 2 → 3
- Evidence: eval/reports/s15e_session.md; docs/upstream/0002-sqlglot-lineage-downstream-set-order.md

## Context

S15a's set-E gold export hashes the full dbt_jira graph, and that hash changed between runs.
sqlglot 30.21.0 `lineage.py:364` collects a projection's source columns with
`set(find_all_in_scope(select, exp.Column))`, so the order of `Node.downstream`, and with it the
order `_walk` yields paths, follows `PYTHONHASHSEED`. `_model_edges` keeps one edge per
(from, to) and replaced the kept edge only on a strictly stronger `(kind rank, HIGH)`. When two
paths tied, the first one seen won, and its steps became `expression`. On dbt_jira, seed 0
against seeds 1, 2 and 3 gave 9, 4 and 8 edges whose `expression` differed. `lines` and every
other field were the same. synthetic_shop was already byte-identical across seeds, because no
tie there has two different step texts.

## Decision

Make the choice total, and leave the walk alone. `_wins(new, new_tie, old, old_tie)` keeps the
strength rule unchanged (kind rank, then HIGH over LOW). On an exact tie the smaller
`_tie_key` wins: `(expression, lines, inputs)`. Each part is normalised to one type (None
becomes `""` or `()`, lines become ints, inputs become strings), so the comparison can't raise
and is a total order. An identical candidate never replaces the kept edge.

Fix 2 (sorting children in `_walk`) was not needed. Fix 1 alone made dbt_jira's graph JSON
identical across seeds 0–3.

## Consequences

- dbt_jira: identical graph JSON under seeds 0–3. Each edge's (file, lines) is the same as
  every old seed build. Two edges (`int_jira__user_metrics.avg_age_currently_open_{days,seconds}`
  ← `resolved_at`) now carry a tied path that none of the old seeds 0–3 happened to pick (all
  four drew the same first path). The new pick is still a path the engine produced.
- synthetic_shop: graph JSON byte-identical to the main build, so the demo bundle is unaffected
  (not rebuilt: no `dlens_version` bump; owner decision in S15e).
- S0 records: 0 differences against the s13c baseline. The agent-code sha (`bfcf97d5…`) and the
  S1 frozen hashes are unchanged.
- Artifact caches built before this change are rebuilt (`BUILDER_VERSION` 3).

## Alternatives rejected

- **Sort children in `_walk`.** It would change the path enumeration everywhere, including the
  order paths are recorded for gaps and constants. That is a larger change than needed when only
  the choice of edge varies.
- **Patch or wrap sqlglot.** sqlglot is pinned and this is upstream behaviour. A local patch
  would have to be kept up through every bump. The observation is filed as a draft instead
  (docs/upstream/0002).
- **Force `PYTHONHASHSEED=0` in the CLI or tests.** It hides the problem. Library callers,
  Streamlit and subprocesses would still vary, and a fixed seed is not a property of the code.
- **Keep every tied path's expression.** It changes the Edge model (spec §7) and the graph
  format to fix what is only a choice between equivalent citations.
