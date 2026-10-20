# 0024. Structured yes/no verdict on `Answer`: `reach_verdict` and `reach_verdict_source`

- Status: Proposed (draft, S11 step 1, 20 Oct 2026; owner decision pending)
- Date: 2026-10-20
- Amends: spec §8 answer schema (additive)
- Implemented in: S11 (field + S1), S12 (S4 sets it)
- Evidence: docs/plans/metrics-design.md M5 and §18; docs/plans/s1-design.md B7

## Context

Metrics-design v1.1 (ADR 0023) scores yes/no questions only on a structured verdict (M5). A prose
heuristic scores phrasing, not correctness. The answer schema has no such field. S0 writes its
verdict in a record-level key (`structured.reach_verdict`). S1 (S11) and S4 (S12) need it in the
shared `Answer` schema, and S4 also needs a record of who set it: the LLM, or code when R9 salvage
replaces the verdict. The S4-raw view must count only the LLM's own value.

## Decision (proposed)

Two additive fields on `Answer`, both defaulting to `null`:

- `reach_verdict: "yes" | "no" | null`: set only on yes/no reachability questions.
- `reach_verdict_source: "llm" | "code" | null`: `llm` when the value comes from the model's draft,
  `code` when code set or replaced it; `null` when `reach_verdict` is `null`.

S1 sets them in S11 (`source = "llm"`). S4's draft schema, prompts and loop are not changed until
S12. `eval/metrics.py` reads this shape and S0's record-level key through one accessor. The S4-raw
view counts a value only when its source is `llm`.

## Consequences

- Old records and presets still load (both fields default to `null`).
- S4 cache keys are unchanged in S11: `AnswerDraft` and `DRAFT_SCHEMA` don't move. New `Answer`
  dumps carry two extra `null` keys.
- The S10 guess of a nested `{value, set_by}` shape is dropped from the metrics accessor. No
  committed record uses it.

## Alternatives rejected

- One nested object `{value, set_by}`: harder for Ollama's grammar and Gemini's schema, and no
  gain over two flat fields.
- A record-level key only (as S0 does): it keeps a scored value out of the public answer schema,
  and the UI could not show it.
- A prose heuristic: rejected by M5 (it scores phrasing, not correctness).
