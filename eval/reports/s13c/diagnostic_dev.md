# S13c post-S13c dev diagnostic (qwen, dev): not a result

> **post-S13c dev diagnostic.** One labelled re-run of the 96 dev questions after the S13c changes (A1, A2, L2, L1, F1 (d1), F6 gate, seed 42). **Not a result; it does not replace the pilot table**, and no change was adjusted in response to it. The honest check is the test set after the 7 Dec 2026 freeze.

| | pilot | post-S13b | post-S13c |
|---|---|---|---|
| agent sha | `a6fb5b2e…` | `77e25642…` | `2a2d9b1e…` |
| model digest | `0edcdef34593` | `0edcdef34593` | `0edcdef34593` |
| sampling | {"num_ctx": 8192, "seed": null, "temperature": 0, "think": false} | {"num_ctx": 8192, "seed": null, "temperature": 0, "think": false} | {"num_ctx": 8192, "seed": 42, "temperature": 0, "think": false} |
| cache hits / misses | 0 / 319 | 0 / 313 | 0 / 324 |
| LLM calls | 319 | 313 | 324 |

## S4 rows (mean [95% CI] (n))

### raw

| row | pilot | post-S13b | post-S13c dev diagnostic |
|---|---|---|---|
| node-set F1 | 0.597 [0.50, 0.69] (68) | 0.597 [0.50, 0.69] (68) | 0.617 [0.52, 0.71] (68) |
| trace F1 | 0.613 [0.48, 0.73] (44) | 0.613 [0.48, 0.73] (44) | 0.635 [0.51, 0.75] (44) |
| impact F1 | 0.568 [0.40, 0.73] (24) | 0.568 [0.40, 0.73] (24) | 0.584 [0.43, 0.74] (24) |
| hallucination rate | 0.005 [0.00, 0.01] (72) | 0.005 [0.00, 0.01] (72) | 0.005 [0.00, 0.01] (76) |
| citation valid (answer) | 0.616 [0.51, 0.73] (73) | 0.616 [0.51, 0.73] (73) | 0.613 [0.50, 0.71] (80) |
| false refusal | 0.115 [0.05, 0.18] (87) | 0.115 [0.05, 0.18] (87) | 0.069 [0.02, 0.13] (87) |
| refusal acc. | 1.000 (9) | 1.000 (9) | 1.000 (9) |
| yes/no | 1.000 (6) | 1.000 (6) | 1.000 (6) |
| chain | 1.000 (2) | 1.000 (2) | 1.000 (2) |
| clarify | 1.000 (1) | 1.000 (1) | 1.000 (1) |
| node-set F1, hop 6+ | 0.373 [0.20, 0.54] (17) | 0.373 [0.20, 0.54] (17) | 0.373 [0.20, 0.54] (17) |

### validated

| row | pilot | post-S13b | post-S13c dev diagnostic |
|---|---|---|---|
| node-set F1 | 0.561 [0.47, 0.66] (68) | 0.578 [0.49, 0.68] (68) | 0.607 [0.52, 0.70] (68) |
| trace F1 | 0.581 [0.45, 0.70] (44) | 0.607 [0.48, 0.72] (44) | 0.637 [0.51, 0.75] (44) |
| impact F1 | 0.524 [0.35, 0.69] (24) | 0.524 [0.35, 0.69] (24) | 0.552 [0.40, 0.71] (24) |
| hallucination rate | 0.000 [0.00, 0.00] (69) | 0.000 [0.00, 0.00] (71) | 0.000 [0.00, 0.00] (77) |
| citation valid (answer) | 0.899 [0.81, 0.97] (69) | 0.901 [0.82, 0.96] (71) | 0.885 [0.82, 0.95] (78) |
| false refusal | 0.149 [0.08, 0.23] (87) | 0.126 [0.06, 0.20] (87) | 0.080 [0.02, 0.14] (87) |
| refusal acc. | 1.000 (9) | 1.000 (9) | 1.000 (9) |
| yes/no | 0.833 (6) | 1.000 (6) | 1.000 (6) |
| chain | 0.500 (2) | 1.000 (2) | 1.000 (2) |
| clarify | 0.000 (1) | 1.000 (1) | 1.000 (1) |
| node-set F1, hop 6+ | 0.364 [0.19, 0.53] (17) | 0.373 [0.20, 0.54] (17) | 0.373 [0.20, 0.54] (17) |

### augmented

| row | pilot | post-S13b | post-S13c dev diagnostic |
|---|---|---|---|
| node-set F1 | 0.625 [0.52, 0.72] (68) | 0.642 [0.54, 0.74] (68) | 0.668 [0.57, 0.76] (68) |
| trace F1 | 0.581 [0.45, 0.70] (44) | 0.607 [0.48, 0.72] (44) | 0.637 [0.51, 0.75] (44) |
| impact F1 | 0.707 [0.52, 0.87] (24) | 0.707 [0.52, 0.87] (24) | 0.724 [0.55, 0.88] (24) |
| hallucination rate | 0.000 [0.00, 0.00] (69) | 0.000 [0.00, 0.00] (71) | 0.000 [0.00, 0.00] (77) |
| citation valid (answer) | 0.914 [0.84, 0.97] (70) | 0.917 [0.85, 0.97] (72) | 0.899 [0.82, 0.96] (79) |
| false refusal | 0.149 [0.08, 0.23] (87) | 0.126 [0.06, 0.20] (87) | 0.080 [0.02, 0.14] (87) |
| refusal acc. | 1.000 (9) | 1.000 (9) | 1.000 (9) |
| yes/no | 0.833 (6) | 1.000 (6) | 1.000 (6) |
| chain | 0.500 (2) | 1.000 (2) | 1.000 (2) |
| clarify | 0.000 (1) | 1.000 (1) | 1.000 (1) |
| node-set F1, hop 6+ | 0.516 [0.30, 0.72] (17) | 0.525 [0.32, 0.72] (17) | 0.525 [0.32, 0.72] (17) |

## Refusals by family (final answers)

| family | pilot | post-S13b | post-S13c dev diagnostic |
|---|---|---|---|
| ask | 5 | 5 | 2 |
| impact | 2 | 1 | 0 |
| trace | 6 | 5 | 5 |
| unanswerable | 9 | 9 | 9 |

**Ask refusals:** pilot 5 / 12, post-S13b 5 / 12, post-S13c 2 / 12. Ask is not re-scored (the AI-scored sheet is frozen).

## Per question (validated), post-S13b → post-S13c dev diagnostic

| id | family | node-set F1 | fully correct | answer kind | moved | record shows |
|---|---|---|---|---|---|---|
| dev-29 | trace | 0.000 → 0.333 | 0.000 → 0.000 | clarification → answered | up / changed | L1 `line_margin in int_order_item_margins` → int_order_item_margins.line_margin |
| dev-40 | trace | 0.000 → 1.000 | 0.000 → 1.000 | clarification → answered | up / changed | L1 `order_id in int_order_profit` → int_order_profit.order_id |
| dev-53 | impact | 0.032 → 0.149 | 0.000 → 0.000 | answered → answered | up / changed | F1 indirect completion first #1, first #2, first #3, first #4 |
| dev-65 | impact | 0.741 → 0.903 | 0.000 → 0.000 | answered → answered | up / changed | F1 indirect completion first #9, first #10, first #11, first #12 |
| dev-66 | impact | 0.000 → 0.077 | 0.000 → 0.000 | refused → answered | up / changed | F6 docs_evidence |
| dev-71 | impact | 0.000 → 0.320 | 0.000 → 0.000 | clarification → answered | up / changed | L1 `customer_id in int_customer_sessions` → int_customer_sessions.customer_id; F1 indirect completion first #1, first #2, first #3 |
| dev-78 | ask | – → – | – → – | refused → answered | up / changed | F6 docs_evidence |
| dev-84 | ask | – → – | – → – | refused → answered | up / changed | F6 docs_evidence |
| dev-86 | ask | – → – | – → – | refused → answered | up / changed | F6 docs_evidence |

**Moved the wrong way:** none.

## Attribution over all 96 (where the record shows the mechanism)

- **F6 (`+docs_evidence`):** dev-66, dev-78, dev-82, dev-84, dev-86
- **F1 (indirect completion):** dev-53, dev-65, dev-71
- **L1 / L2 (linker):** dev-29, dev-38, dev-39, dev-40, dev-45, dev-60, dev-68, dev-69, dev-71, dev-75, dev-77, dev-96

## S0-linked (hybrid on), no LLM: pilot vs post-S13c

| row | pilot | post-S13c |
|---|---|---|
| node-set F1 | 0.809 [0.71, 0.90] (68) | 0.882 [0.81, 0.96] (68) |
| trace F1 | 0.864 [0.75, 0.95] (44) | 0.909 [0.82, 0.98] (44) |
| impact F1 | 0.708 [0.50, 0.88] (24) | 0.833 [0.67, 0.96] (24) |
| refusal acc. | 0.889 (9) | 1.000 (9) |
| false refusal | 0.013 [0.00, 0.05] (75) | 0.013 [0.00, 0.05] (75) |
| clarify | 1.000 (1) | 1.000 (1) |

## Notes (hand-written, 22 Oct 2026, from the records above)

- **Validated citation validity fell, 0.901 (n = 71) → 0.885 (n = 78), and only through newly
  answered questions.**
  - Seven questions now answer: dev-29, 40, 66, 71, 78, 84 and 86.
  - Five of them score 1.0.
  - The two F6 docs-based Ask answers, dev-84 and dev-86, score 0.0 under metrics M7.
  - No question that answered before changed its citation validity.

  Recorded, not acted on: no change is adjusted in response to this run.
- **dev-82** reached the F6 step (`+docs_evidence`), and then the model itself refused on the docs
  evidence. That is a model refusal, not "no lineage evidence".
- **dev-87** stays refused by the gate (no linker candidate), as measured in the design.
  Ask refusals: 5 → 2 of 12.
- **dev-65 (F1):** the added edges are direct, but each bridge runs through the claim's own cited
  JOIN edge, which the pre-S13c direct-only adjacency could not use.
- **L1 / L2 marks** cover every question whose tool phase hit a `qualified` candidate or an
  unknown dotted model. Only dev-29, 40 and 71 moved because of them in this run.
- **The seed** makes this run the first with `seed: 42`. Every call was fresh (0 cache hits), so
  run-to-run differences from the S13b diagnostic include the seed change itself; no per-question
  claim is made about it.
- **S0-linked hybrid on (no LLM):** refusal accuracy is back to 1.000. dev-93 is refused (L2),
  and dev-29, 40, 55, 56, 71 answer (L1).
