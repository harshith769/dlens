# S0 graph oracle on the 96 dev questions (S10 step 4)

metrics-design 1.1 · metrics.py 1.1.0 · records from S0 at commit 4a5296d · `make eval-s0`
(no LLM call). Full reports: `s0_gold_dev.md` / `.json`, `s0_linked_dev.md` / `.json`. Ask (12)
is n/a for S0, so 84 questions have records. Primary modes per Appendix A.

| metric | S0-gold | S0-linked (hybrid off) |
|---|---|---|
| node-set F1 (pooled, n = 68) | 1.000 [1.00, 1.00] | 0.868 [0.78, 0.94] |
| trace F1 (n = 44) | 1.000 [1.00, 1.00] | 0.909 [0.82, 0.98] |
| impact F1 (n = 24) | 1.000 [1.00, 1.00] | 0.792 [0.62, 0.92] |
| yes/no verdict accuracy (n = 6) | 1.000 | 1.000 |
| refusal accuracy (n = 9) | 1.000 | 1.000 |
| false-refusal rate (n = 75) | 0.000 | 0.107 [0.04, 0.17] |
| chain correct (n = 2) / clarify correct (n = 1) | 1.000 / 1.000 | 1.000 / 1.000 |
| false-premise explicit rejection (n = 4) | 1.000 | 1.000 |
| path node coverage (n = 29) | 1.000 [1.00, 1.00] | 0.897 [0.76, 1.00] |
| fully correct (n = 84) | 1.000 | 0.893 [0.82, 0.95] |
| hallucinated-node rate | 0.000 | 0.000 |
| citation validity, per answer | 1.000 [1.00, 1.00] (n = 71) | 1.000 [1.00, 1.00] (n = 63) |
| citation validity, per citation | 982 / 982 | 882 / 882 |
| citation coverage | 1.000 | 1.000 |

S0-gold scores 1.0 on every metric in the primary mode. The DLens graph agrees with the gold spec
on every dev answer, including the indirect-only questions (dev-70, 71, 74), the 6+ hop bucket
and all three exposure-reaching cases. Per-answer citation validity is over 71 answers: the 3
correct "No" verdicts (dev-10, 75, 76) have nothing to cite and are n/a under M7 v1.1.

## Every value below 1.0, with its reason

Reasons are reported, never fixed by changing a metric, the gold or the engine.

**S0-gold:** none.

**S0-linked (hybrid off)**

| id | metric | reason |
|---|---|---|
| dev-21, 28, 41 (upstream); dev-27 (computed); dev-51, 57, 62, 63 (impact) | refused → 0 on every set metric; false refusal | Description-worded questions ("the column documented as '…'"). Without the hybrid stage the linker has no stage that matches description text, so it finds no candidate. These are the 8 description questions in the trace / impact rows; this is the linker loss the hybrid stage exists for. |
| dev-55 (impact) | clarification → 0 | "id in raw product costs": 5 candidates within the ambiguity gap (0.865–0.870: stg_product_costs.product_cost_id, int_product_costs_current.product_id, stg_product_costs.product_id, raw_product_costs.id, raw_product_costs.product_id). More than 3 tied, so the code policy asks for clarification. Linker loss. |

dev-46 ("order month", gold `clarify`) is now correct for S0-linked: the code policy answers per
candidate and names both gold candidates, which M9 v1.1 accepts.

No hallucinated nodes. No citation fails the on-disk re-check. No R3 disagreements (S0 runs no
validator, so R3 checked nothing). No truncated payloads. 10 mentions removed by the negation rule
in each variant: the false-premise "It does not use X." sentences and the "No: A does not reach
B." yes/no sentences, as designed.

## Changes from metrics 1.0.1 (same records, re-scored with 1.1.0)

| report | metric | 1.0.1 → 1.1.0 |
|---|---|---|
| S0-gold | citation validity per answer | 0.959 [0.91, 1.00] (n = 74) → 1.000 [1.00, 1.00] (n = 71) |
| S0-linked | citation validity per answer | 0.955 [0.89, 1.00] (n = 66) → 1.000 [1.00, 1.00] (n = 63) |
| S0-linked | clarify correct (n = 1) | 0.000 → 1.000 (dev-46) |
| S0-linked | fully correct (n = 84) | 0.881 [0.81, 0.94] → 0.893 [0.82, 0.95] |

## Notes

- Latency (S0, no LLM): p50 0.1 ms, p95 9.8 ms over 84 runs; 0 tokens, 0 LLM calls.
- Records: `eval/runs/s0/` (1.2 MB for both variants, under the 2 MB target), each with a
  manifest (hybrid off, max depth 50, dev.jsonl sha256, git commit). Not regenerated for 1.1.
- The linker-test flag (21 questions) splits node-set F1 in the full reports.
