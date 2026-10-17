# 0022. resolve_entity v2: additive payload key, match value and side-record fields

- Status: Accepted (owner, 17 Oct 2026)
- Date: 2026-10-17
- Amends: spec §8 (Tools table, `resolve_entity` row; additive only)
- Implemented in: S08 (B2)
- Evidence: docs/plans/linker-design.md §5

## Context

Linker v2 adds stages (exact → normalised → hybrid over column cards) and an explicit no-match
threshold. The hybrid stage needs the `retrieval` extra and a built index. The core and demo
installs have neither, so `resolve_entity` must say when hybrid was unavailable. Spec §7 makes
the tool's output shape a stable public interface, so any change has to be additive.

## Decision

The LLM payload stays `{query, candidates: [{id, kind, match, score}], ambiguous, notes?}`.
There are two additive changes:
- `match` gains the value `hybrid`. `exact`, `normalised` and `fuzzy` keep their meaning; both
  v2 normalised tiers (surface and rewritten) report `normalised`.
- A new optional key `hybrid`: `"unavailable"` when the toolbox has no index, `"used"` when
  stage 3 ran, and absent when the index exists but stage 3 was not needed.

The side record (not shown to the LLM; it goes to the run record and the UI) keeps `scores` and
adds:
- `parts`: per candidate `{stage, tier, base, model_bonus, layer, rules, rrf_norm?, bm25_rank?,
  dense_rank?, cosine?}`
- `closest`: up to 3 ids below the no-match threshold. This is present only when `candidates` is
  empty, and it is **display-only**: it never enters the LLM payload, so the model cannot adopt
  a below-threshold id.

An empty `candidates` list is handled exactly as before. The agent loop's ambiguity policy and
unknown-column refusal are unchanged.

## Consequences

- Readers of v1 payloads (context.py compaction, evidence.py, the UI, presets) keep working,
  because no field is removed or renamed.
- Demo payloads always carry `"hybrid": "unavailable"`, about 6 tokens per call, well inside the
  ~3K cap.
- Score values change (tiers, bounded fuzzy). The `score` field is unchanged as a shape, but the
  recorded presets that call resolve_entity are re-recorded (S08 gate 2).

## Alternatives rejected

- **Score parts in the LLM payload:** it costs tokens on every call, and the model has no use
  for them.
- **`closest` in the payload:** it invites the model to answer about a column the linker rejected.
- **A new tool (`resolve_entity_v2`):** two tools with overlapping jobs, and every prompt would
  need changing.
