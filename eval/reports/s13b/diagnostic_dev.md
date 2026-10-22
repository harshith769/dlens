# S13b post-fix dev diagnostic (qwen, dev): not a result

> **post-fix dev diagnostic.** One labelled re-run of the 96 dev questions after the approved post-pilot fixes (F2, F3, F4, F5; F1 and F6 deferred). **Not a result; it does not replace the pilot table**, and no fix was adjusted in response to it. The honest check is the test set after the 7 Dec 2026 freeze. Every number below is a post-fix dev diagnostic number unless its column says pilot.

| | pilot qwen S4 (S13 table) | post-fix dev diagnostic |
|---|---|---|
| records | `s4-qwen3-4b-instruct-2507-q4-k-m-dev.jsonl` | `s13b-qwen3-4b-instruct-2507-q4-k-m-dev.jsonl` |
| agent sha | `a6fb5b2e…` | `77e25642…` |
| model digest | `0edcdef34593` | `0edcdef34593` |
| sampling | {"num_ctx": 8192, "seed": null, "temperature": 0, "think": false} | {"num_ctx": 8192, "seed": null, "temperature": 0, "think": false} |
| index | index reused | index reused |
| cache (hits / misses) | 0 / 319 | 0 / 313 |
| records / LLM calls | 96 / 319 | 96 / 313 |
| purpose | – | diagnostic, post-fix dev; not a result; does not replace the pilot table |

## Rows (mean [95% CI] (n)), pilot vs post-fix dev diagnostic

| row | raw: pilot | raw: post-fix dev diagnostic | validated: pilot | validated: post-fix dev diagnostic | augmented: pilot | augmented: post-fix dev diagnostic |
|---|---|---|---|---|---|---|
| node-set F1 | 0.597 [0.50, 0.69] (68) | 0.597 [0.50, 0.69] (68) | 0.561 [0.47, 0.66] (68) | 0.578 [0.49, 0.68] (68) | 0.625 [0.52, 0.72] (68) | 0.642 [0.54, 0.74] (68) |
| trace F1 | 0.613 [0.48, 0.73] (44) | 0.613 [0.48, 0.73] (44) | 0.581 [0.45, 0.70] (44) | 0.607 [0.48, 0.72] (44) | 0.581 [0.45, 0.70] (44) | 0.607 [0.48, 0.72] (44) |
| impact F1 | 0.568 [0.40, 0.73] (24) | 0.568 [0.40, 0.73] (24) | 0.524 [0.35, 0.69] (24) | 0.524 [0.35, 0.69] (24) | 0.707 [0.52, 0.87] (24) | 0.707 [0.52, 0.87] (24) |
| hallucination rate | 0.005 [0.00, 0.01] (72) | 0.005 [0.00, 0.01] (72) | 0.000 [0.00, 0.00] (69) | 0.000 [0.00, 0.00] (71) | 0.000 [0.00, 0.00] (69) | 0.000 [0.00, 0.00] (71) |
| citation valid (answer) | 0.616 [0.51, 0.73] (73) | 0.616 [0.51, 0.73] (73) | 0.899 [0.81, 0.97] (69) | 0.901 [0.82, 0.96] (71) | 0.914 [0.84, 0.97] (70) | 0.917 [0.85, 0.97] (72) |
| false refusal | 0.115 [0.05, 0.18] (87) | 0.115 [0.05, 0.18] (87) | 0.149 [0.08, 0.23] (87) | 0.126 [0.06, 0.20] (87) | 0.149 [0.08, 0.23] (87) | 0.126 [0.06, 0.20] (87) |
| yes/no | 1.000 (6) | 1.000 (6) | 0.833 (6) | 1.000 (6) | 0.833 (6) | 1.000 (6) |
| chain | 1.000 (2) | 1.000 (2) | 0.500 (2) | 1.000 (2) | 0.500 (2) | 1.000 (2) |
| clarify | 1.000 (1) | 1.000 (1) | 0.000 (1) | 1.000 (1) | 0.000 (1) | 1.000 (1) |
| node-set F1, hop 6+ | 0.373 [0.20, 0.54] (17) | 0.373 [0.20, 0.54] (17) | 0.364 [0.19, 0.53] (17) | 0.373 [0.20, 0.54] (17) | 0.516 [0.30, 0.72] (17) | 0.525 [0.32, 0.72] (17) |

## Refusals by family (final answers; the validated view)

| family | pilot | post-fix dev diagnostic |
|---|---|---|
| ask | 5 | 5 |
| impact | 2 | 1 |
| trace | 6 | 5 |
| unanswerable | 9 | 9 |

**Ask refusal count:** pilot 5 of 12, post-fix dev diagnostic 5 of 12. Ask is not re-scored (the AI-scored sheet is frozen).

## Per question (validated view), pilot → post-fix dev diagnostic

First drafts identical to the pilot's: 88 of 96 (temperature 0; a differing draft means the model output itself changed, not a fix).

| id | family | node-set F1 | fully correct | answer kind | moved |
|---|---|---|---|---|---|
| dev-16 | trace | 0.000 → 1.000 | 0.000 → 1.000 | answered → answered | up / changed |
| dev-45 | trace | 0.182 → 0.333 | 0.000 → 0.000 | answered → answered | up / changed |
| dev-46 | trace | – → – | 0.000 → 1.000 | refused → answered | up / changed |
| dev-75 | impact | – → – | 0.000 → 1.000 | refused → answered | up / changed |

**Moved the wrong way:** none.

## Per-fix attribution (only where the record shows the mechanism)

- **F3** (refused regenerate → salvage; `stop_reason` `+regenerate_refused`): dev-75.
- **F4** (5–6 hex prefix repaired by R2r): dev-16: first: e_81a3f → e_81a3f693.
- **F2** (counterfactual replay of this record's drafts with the alias skip off): dev-30: first: claim 0, answer_text pass only through the alias skip; second: claim 0, answer_text pass only through the alias skip; dev-44: first: claim 1, answer_text pass only through the alias skip; dev-45: first: claim 0, answer_text pass only through the alias skip; dev-46: first: claim 0, claim 1, answer_text pass only through the alias skip.
- **F5** (Gemini transport errors): not exercised by a local qwen run (0 steps).

## Notes (hand-written, 22 Oct 2026, from the records above)

- **The 8 differing first drafts are model variation, not a fix.** They are dev-17, 18, 20, 21,
  22, 24, 27 and 28.
  - For each, the tool-phase texts and the answer-phase evidence equal the pilot's, and no
    prompt changed: `test_s4` pins the answer-system, schema, repair and regenerate hashes
    against the pilot manifest.
  - Only the model's answer draft differs. This is run-to-run output variation of the local
    model at temperature 0, not seen in S13's S1 re-run.
  - dev-24 and dev-27 differ also in whether a regenerate followed.
  - None of the 8 changed its validated node-set F1, its fully-correct value or its answer
    kind.
- **dev-45's rise (0.182 → 0.333) comes through F2 on a claim the prep audit classed
  gold-inconsistent** (`margins_monthly.contribution_margin`, a derived-table alias). The class
  comes only from the alias token. The claim's real node, `fct_monthly_finance.contribution_margin`,
  is in the gold set (post-pilot-fixes.md, F2).
- **Calls:** 313 vs 319 in the pilot. The difference is fewer regenerates: dev-16 and dev-46
  now pass on the first draft.
- **Unchanged by design (deferred):**
  - The dev-53 / dev-65 R8 drops remain (F1).
  - The 11 "no lineage evidence" refusals remain: 5 Ask, dev-41, dev-66 and dev-93–96 (F6).
