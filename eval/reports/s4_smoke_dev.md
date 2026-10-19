# S4 smoke records re-scored with metrics v1.1 (S10 step 5, report only)

metrics-design 1.1 · metrics.py 1.1.0 · zero LLM calls (the 96 records from the S09 eval-smoke
run were read from the local run directory; nothing was re-run). Full reports:
`s4_smoke_dev_{raw,validated,augmented}.{md,json}`.

**What these records are.** 96 S4 answers from 18 Oct 2026 (`make eval-smoke`, local
qwen3:4b-instruct-2507-q4_K_M, linker hybrid stage off, 77 uncached / 19 cached runs). They were
written before S10, so they have no manifest (a legacy manifest was built from the records' own
fields) and none of the S12 fields. **This is not the pilot table** (v0.3 done-when 5): no S1, no
Gemini, pre-S12 system. No definition was changed after these numbers were seen.

| metric | S4-raw | S4-validated | S4-augmented |
|---|---|---|---|
| node-set F1 (pooled, n = 68) | 0.469 [0.36, 0.57] | 0.464 [0.36, 0.57] | = validated |
| trace F1 (n = 44) | 0.528 [0.39, 0.67] | 0.536 [0.40, 0.67] | = validated |
| impact F1 (n = 24) | 0.361 [0.20, 0.53] | 0.332 [0.18, 0.51] | = validated |
| yes/no verdict accuracy (n = 6) | 0.000 | 0.000 | 0.000 |
| refusal accuracy (n = 9) | 1.000 | 1.000 | 1.000 |
| false-refusal rate (n = 87, incl. Ask) | 0.230 [0.15, 0.32] | 0.230 [0.15, 0.32] | = validated |
| chain correct (n = 2) / clarify correct (n = 1) | 1.000 / 0.000 | 1.000 / 0.000 | = validated |
| false-premise explicit rejection (n = 4) | 0.250 | 0.250 | = validated |
| path node coverage (n = 29) | 0.552 [0.38, 0.72] | 0.517 [0.34, 0.69] | = validated |
| fully correct (n = 84) | 0.345 [0.24, 0.45] | 0.333 [0.24, 0.44] | = validated |
| hallucinated-node rate | 0.006 [0.00, 0.02] | 0.000 | = validated |
| answers with ≥ 1 hallucinated node | 0.030 (2 / 66) | 0.000 | = validated |
| citation validity, per answer (n = 66) | 0.591 [0.47, 0.70] | 0.924 [0.86, 0.98] | = validated |
| citation validity, per citation | 280 / 305 | 259 / 262 | = validated |
| citation coverage | 1.000 | 1.000 | = validated |

Latency (uncached, n = 77): p50 5.3 s, p95 23.3 s. Tokens per question: mean 2,640, p95 6,343;
LLM calls per question: mean 3.06.

## How to read it

- **yes/no 0 / 6 is structural, not a measured skill.** M5 scores only the structured
  `reach_verdict`, which S4 does not emit until S12, so every yes/no answer scores 0. The
  labelled first-sentence heuristic (diagnostic only) reads dev-10 "no", dev-74 "no", dev-76 "no",
  and nothing for dev-72, 73, 75.
- **S4-augmented equals S4-validated:** no claim carries `origin: augmented` before S12 (G1).
- **Indirect-only gold:** dev-70, dev-71 (impact) and dev-74 (yes/no) score 0 in every mode. S4's
  tools are direct-only today (S12 requirement).
- **Description-worded questions:** node-set F1 0.000 (n = 8) in both views. All 8 were refused
  (hybrid stage off), as for S0-linked.
- **Breakdowns (validated, node-set F1):** hop 1: 0.500 (n = 14), 2–3: 0.562 (19), 4–5: 0.576
  (16), 6+: 0.275 (17), indirect-only: 0.000 (2). Linker-test-seen 0.316 (n = 14) vs not seen
  0.502 (n = 54).
- **False premise:** dev-49 rejected; dev-17 and dev-50 asserted (case O); dev-18 not rejected
  (case U).
- **Hallucinations (raw only):** dev-09 (6 `fct_orders.*` names that do not exist) and dev-37
  (`fct_orders.order_status`). The validator removed both (R4).
- **Ambiguity:** dev-46 answered per candidate where the gold says clarify (the policy/gold
  disagreement reported in `s0_dev.md`).

## Changes from metrics 1.0.1 (same records, re-scored with 1.1.0)

**No headline value changed** in any of the three views. The only change is a diagnostic:
R3 disagreements in the raw view 25 → 3 (validated: 3 → 3). The 22 removed were cited ids with no
citation attached (miscopied ids that fail R2 and never reach R3); v1.1 counts only ids the R3
check ran on. The 3 left are excerpt citations (`s_`) that R3 passes by text hash and metrics
fails because the cited lines name no column of the claim, a real difference between the two
checks, as M7 intends.

The two other 1.1 rules do not apply to these records: S4 emits no structured `reach_verdict`
before S12, so no answer is n/a for per-answer citation validity; and S4 refused dev-46 ("no
lineage evidence was found"), so clarify correct stays 0.000 under either rule.
