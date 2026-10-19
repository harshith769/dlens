# S0 graph oracle on the 96 dev questions (S10 step 4)

metrics-design 1.0 · metrics.py 1.0.1 · records from S0 at commit 4a5296d · `make eval-s0`
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
| chain correct (n = 2) / clarify correct (n = 1) | 1.000 / 1.000 | 1.000 / 0.000 |
| false-premise explicit rejection (n = 4) | 1.000 | 1.000 |
| path node coverage (n = 29) | 1.000 [1.00, 1.00] | 0.897 [0.76, 1.00] |
| fully correct (n = 84) | 1.000 | 0.881 [0.81, 0.94] |
| hallucinated-node rate | 0.000 | 0.000 |
| citation validity, per answer | 0.959 [0.91, 1.00] (n = 74) | 0.955 [0.89, 1.00] (n = 66) |
| citation validity, per citation | 982 / 982 | 882 / 882 |
| citation coverage | 1.000 | 1.000 |

S0-gold scores 1.0 on every set and verdict metric in the primary mode. The DLens graph agrees
with the gold spec on every dev answer, including the indirect-only questions (dev-70, 71, 74),
the 6+ hop bucket and all three exposure-reaching cases.

## Every value below 1.0, with its reason

Reasons are reported, never fixed by changing a metric, the gold or the engine.

**S0-gold**

| id | metric | reason |
|---|---|---|
| dev-10, dev-75, dev-76 | citation validity per answer = 0 | Correct "No" verdicts. No path exists, so there is no edge to cite, and M7 (a) counts an answered answer with zero citations as invalid. This follows the approved definition. Spec §11.4 says "a correct No has nothing to cite"; **owner question**: should answered yes/no "No" answers be excluded from per-answer citation validity (an M7 amendment, version 1.1)? Not changed here. |

**S0-linked (hybrid off)**, everything above plus:

| id | metric | reason |
|---|---|---|
| dev-21, 28, 41 (upstream); dev-27 (computed); dev-51, 57, 62, 63 (impact) | refused → 0 on every set metric; false refusal | Description-worded questions ("the column documented as '…'"). Without the hybrid stage the linker has no stage that matches description text, so it finds no candidate. These are the 8 description questions in the trace / impact rows; this is the linker loss the hybrid stage exists for. |
| dev-55 (impact) | clarification → 0 | "id in raw product costs": 5 candidates within the ambiguity gap (0.865–0.870: stg_product_costs.product_cost_id, int_product_costs_current.product_id, stg_product_costs.product_id, raw_product_costs.id, raw_product_costs.product_id). More than 3 tied, so the code policy asks for clarification. Linker loss. |
| dev-46 (ambiguous, gold `clarify`) | clarify correct = 0 | "order month": 2 tied candidates (0.94 each) on different branches. The code ambiguity policy (spec §8: "≤ 3 candidates → answer per candidate") answers per candidate; the dev gold verdict is `clarify`. **Owner question:** the gold (questions-design §3: different branches → clarification) and the spec §8 policy disagree for 2–3 candidates on different branches. Either the gold or the policy should change; neither is changed here. |
| dev-10, dev-75, dev-76 | citation validity per answer = 0 | As for S0-gold. |

No hallucinated nodes. No citation fails the on-disk re-check. No R3 disagreements (S0 has no
validator run). No truncated payloads. 10 mentions removed by the negation rule in each variant:
the false-premise "It does not use X." sentences and the "No: A does not reach B." yes/no
sentences, as designed.

## Notes

- Latency (S0, no LLM): p50 0.1 ms, p95 9.8 ms over 84 runs; 0 tokens, 0 LLM calls.
- Records: `eval/runs/s0/` (1.2 MB for both variants, under the 2 MB target), each with a
  manifest (hybrid off, max depth 50, dev.jsonl sha256, git commit).
- The linker-test flag (21 questions) splits node-set F1 as S0-gold 1.000 / 1.000 and is in the
  full reports.
