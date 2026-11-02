# S15e session report: deterministic lineage on tied two-branch paths

**Date:** 2 Nov 2026. **Branch:** `s15-engine-determinism` from main 33c0305 (not merged; the
owner merges). **Plan:** the approved S15e plan with owner amendments A1 (four seeds) and A2
(total tie key plus a None-expression unit test). It names `src/dlens/lineage` (rule 9).

## Status

| item | state |
|---|---|
| Fix 1: total tie-break in `_model_edges` | done, 39de487 |
| Fix 2: sort children in `_walk` | **not needed** (fix 1 alone passes acceptance) |
| Golden fixture `tied_two_branch` + four-seed subprocess test | done, 39de487; fails on the old code (below) |
| Unit tests for `_tie_key` / `_wins` (A2) | done, 39de487 (`tests/unit/test_lineage.py`) |
| `BUILDER_VERSION` 2 → 3 | done, 39de487 |
| Demo bundle rebuild | **skipped, owner decision** (below) |
| docs/explain/lineage.md section + explain-back Q8; support matrix regenerated | done, 39de487 |
| ADR 0030, CHANGELOG, docs/upstream/0002 | done, e5e14d8 |
| Agent sha | `bfcf97d5d56c8d873189bdcf68a62666bb095868d34ad23e1ac2aa998537aef5` (unchanged) |
| Cloud LLM calls | **0**. No `.env` read |
| Frozen / draft question files | not opened |

## The fix
`_wins(new, new_tie, old, old_tie)` keeps the strength rule (kind rank, then HIGH over LOW).
An exact tie goes to the smaller `_tie_key(expression, lines, inputs)`, with None normalised to
`""` / `()`, lines to ints and inputs to strings. Path enumeration is unchanged.

## Old code fails the new test (A1)
`tied_two_branch` reads `orders.amt` through `lhs` (`amt * 2 as amt_x`) and `rhs`
(`amt - 1 as amt_y`); output `lhs.amt_x + rhs.amt_y as amt_mix`. On 33c0305:

```
seed 0: lhs.amt_x + rhs.amt_y AS amt_mix <- base.amt * 2 AS amt_x <- orders.amt AS amt
seed 1: lhs.amt_x + rhs.amt_y AS amt_mix <- base.amt * 2 AS amt_x <- orders.amt AS amt
seed 2: lhs.amt_x + rhs.amt_y AS amt_mix <- base.amt - 1 AS amt_y <- orders.amt AS amt
seed 3: lhs.amt_x + rhs.amt_y AS amt_mix <- base.amt - 1 AS amt_y <- orders.amt AS amt

E   AssertionError: PYTHONHASHSEED=2 differs from 0
1 failed
```

The differing pairs are 0/2, 0/3, 1/2 and 1/3. Pair 0/1 agrees, so a two-seed test (0, 1)
would have passed on the old code. A1's four seeds catch it.

The first draft of the fixture used plain pass-through branches (`select id, amt from base`).
Both paths then print the same expression, so the old code could not fail on it. The branches
were changed to compute different things (both still TRANSFORMATION). The expected edges were
the same before and after that change, and they matched the engine on the first run.

## Acceptance

| check | result |
|---|---|
| dbt_jira full graph JSON, PYTHONHASHSEED 0–3 | **identical** (old code: seed 0 vs 1/2/3 differ in 9/4/8 edges, `expression` only) |
| synthetic_shop graph JSON vs the main build | **byte-identical** (no field differs; `BUILDER_VERSION` is not in graph.json) |
| `scripts/check_s0_stable.py` vs s13c baseline | s0-gold 84 / s0-linked 84 records, **0 differ** outside `timings.total_ms` |
| (file, lines) of every edge | dbt_jira 761 edges: **0 differ** from each old seed build; synthetic_shop 363 edges: 0 differ |
| other graph keys (nodes, indirect, parse_report, models, depends_on, consumes, exposures) | equal to every old build, both corpora |
| `s4.agent_code_sha256()` | `bfcf97d5…` (unchanged) |
| `s1.frozen_hashes()` | equal to main's |
| src/dlens/agent, retrieval, eval/metrics.py, eval/systems | no change |
| `make lint`, `make test` | pass (1732 passed, 19 skipped); existing golden tests unchanged |

Note: on dbt_jira, 2 edges (`int_jira__user_metrics.avg_age_currently_open_{days,seconds}` ←
`jira__issue_enhanced.resolved_at`) now carry a tied path that none of old seeds 0–3 picked.
All four old seeds drew the same first path for them. The new pick is the smallest-key path
among the ones the engine produced. Lines are the same.

## Demo bundle: not rebuilt (owner decision)
The committed `demo/synthetic_shop/graph.json` is the v0.2.0 build (format 2). A fresh build on
main already differs from it in format and in 248 edges, because of S04–S14 engine work. Those
differences are not from this change. This change leaves the synthetic_shop graph byte-identical
to main's build and does not bump `dlens_version`. So, by owner decision, the bundle and the
presets stay as they are until the release rebuild. Demo tests pass (26).

## Not done / for the owner
- Spec §0 has no row for ADR 0030. Add one if you want it there. ADR 0030's status is
  "Proposed" until you approve it.
- docs/upstream/0002 is a draft and has not been filed.
- The set-E gold hash work on `s15-test-drafts` can be picked up again after this merges.

## Commits
- 39de487 fix(lineage): total tie-break in _model_edges (S15e)
- e5e14d8 docs(s15e): ADR 0030, changelog, sqlglot set-order note
- this report

## CI
See the push below. The result goes to the owner at the STOP.
