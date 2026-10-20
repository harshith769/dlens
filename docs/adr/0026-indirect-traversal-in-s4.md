# 0026. Indirect traversal in S4's tools, R3 by edge kind, R9 in direct + indirect mode

- Status: Accepted (owner, 20 Oct 2026; S12 Phase 2). Spec §0 row 33.
- Date: 2026-10-20
- Amends: spec §8 tools (defaults now honoured), validator R3, R8c and R9; ADR 0020's
  "tools, validator, UI and demo stay direct-only until S10/S12"
- Implemented in: S12a (A5)
- Evidence: docs/plans/s12-design.md A5 (mode table, payload measurements); metrics-design M4, M7

## Context

Metrics M4 makes direct + indirect the primary mode for the impact family (30 dev questions) and
direct for the trace family (45). S4's tools, R3 and R9 traverse direct edges only, so
indirect-only gold (dev-70, dev-71) and a direct-"no" / indirect-"yes" verdict (dev-74) are out of
S4's reach by construction. Uncapped indirect impact payloads exceed the 1,500-token tool cap on
4 of the 5 largest dev impact questions in today's per-item shape.

## Decision

- **Modes:** `trace_upstream` defaults to direct, `impact_downstream` to direct + indirect (spec
  §7/§8 defaults, now honoured); the code-made `r_` reachability fact checks direct + indirect for
  its verdict and states the direct reading too. The flag is not advertised to the LLM. No `src/`
  code uses metrics' M4 wording rule.
- **Impact payload shape:** full dotted `model.column` ids with one `via` edge id each, grouped
  by (depth, kind); the same grouping in the answer-phase evidence. The full per-column set stays
  in `side_records`. Above the tool cap, columns are cut in a fixed order (depth, then model,
  then column), each cut group leaves one visible line "+K more columns in <model> (<kind>)",
  the payload is flagged `truncated`, and the full set stays in `side_records`. Columns are
  never dropped silently. (Shape B chosen by the owner, 20 Oct 2026.)
- **Indirect edges are citable:** ids as for direct edges; records carry `key` and
  `indirect: true`; citations are checked by kind (the `from` name, or the clause key under
  metrics M7's CTE / derived-alias guard).
- **Validator:** R3 checks by edge kind (direct → `to`, indirect → `from` / guarded key),
  matching M7 (iv); R8c bridges over direct edges only; R9's fact uses direct + indirect.
- **Pinned call sites** that stay direct carry a recorded decision id (`_chain_end`:
  A5-CHAIN; chunk meta: A5-CHUNK-META), enforced by an allowlist in
  `tests/unit/test_traversal_calls.py`. Every `.upstream(` / `.downstream(` call in `src/` passes
  `include_indirect` explicitly; a literal `False` needs an allowlist entry with its decision id.
- **A5-IMPACT-DIRECT-LABEL / impact group labels:** a column is in a `[direct]` group only if an
  all-direct path reaches it, at its direct depth (a second, direct-only traversal decides this;
  allowlisted). Otherwise its label is the kind of the FIRST indirect hop on its shortest
  (all-hop) path, and its depth is that path's length. A column reachable both ways appears once,
  under `[direct]`. `side_records` keep the full via chain.
- **A5-R9-DIRECT-READING:** the fact's direct reading (`direct_reaches`, `direct_hops`) is the
  shortest path over DERIVES edges, so the fact text can state both readings. Not a traversal
  call; recorded in the allowlist test's docstring.
- Decided options: s12-design A5.1 (i) family defaults; R9 fact mode (a).

## Consequences

- Answer-phase evidence grows on impact questions (measured: 895–1,094 est. tokens for the five
  52–65-column dev questions, inside a 2,409-token answer budget).
- Every S4 tool-phase cache key for impact calls changes; the next S4 run is a fresh local run.
- The demo changes only when its presets are re-recorded (S15).

## Alternatives rejected

- Prefix-once grouping (bare column names under a model heading): ~20–30% smaller, but it invites
  bare-name prose, which M3 never counts and R4 cannot check.
- Advertising `include_indirect` to the LLM: more tokens on every tool call and a per-question
  mode choice by a 4B model.
- Keeping R3 on the `to` name: it would reject indirect citations metrics M7 accepts.
