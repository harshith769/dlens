# Explain: the v0.2 dev set and dev report (`eval/questions/dev.jsonl`, `scripts/dev_report.py`)

## What it is
20 hand-written questions on `corpora/synthetic_shop` (v0.1, 15 models), used to check that the
v0.2 agent answers with valid citations (spec §14: "Live demo answers 20 dev questions with valid
citations") and to measure validator behaviour, R8 above all. `make eval-smoke` runs it on local
Ollama with the LLM cache in `eval/cache`, so a re-run costs no model calls and no quota.

| Mix | n | ids |
|---|---|---|
| Upstream trace, 1 / 2–3 / 4–5 / 6+ hops | 2 / 2 / 1 / 1 | dev-01..06 |
| Downstream impact (one yes/no reachability, answer "no") | 4 | dev-07..10 |
| "How is X computed" | 3 | dev-11..13 |
| Abbreviation / paraphrase wording | 2 | dev-14, dev-15 |
| Same-chain ambiguous name (chain mode) | 1 | dev-16 |
| False premise with real columns | 2 | dev-17, dev-18 |
| Nonexistent column | 1 | dev-19 |
| Trap (`SELECT *` + `UNION ALL`) | 1 | dev-20 |

**Never reuse a dev question in the frozen test set.** The test questions (spec §11.2, frozen 7 Dec)
will be written from the v0.3 corpus (40–60 models). The split is by column, so a test question
must not target a dev question's `target` column either. The dev set is also tuned on: prompts,
the validator and the completion decision all looked at it. That is exactly why it can never
measure them.

## How gold was derived
Gold comes **only** from `DESIGN.md`, `lineage_spec.yml` and `traps.yml`, never from parser or
graph output (spec §11.1, CLAUDE.md hard rule). For each question the edges were picked by hand as
`lineage_spec.yml` line numbers. A throwaway helper copied `from`/`to`/`kind` from exactly those
lines of the gold spec, so there are no typos, and every kind was checked against the DESIGN.md
row. `source_lines` records every spec, DESIGN.md and traps.yml line used.

Schema (one JSON object per line):
- `id, corpus, split, type` (§11.2: trace / impact / ask / unanswerable), `subtype, question`;
- `target`: the queried column; `hop_depth`: DESIGN.md's longest path (up to a seed for trace,
  down from the source for impact, 1 for "computed"); `hop_bucket`: 1, 2-3, 4-5, 6+;
- `wording` (identifier / description) and `traps`;
- `gold`: `verdict`, `edges[{from, to, kind, line}]`, and optionally `answer` (yes/no), `facts`,
  `also_ok` (edges that are fine to cite but are not gold), `note`;
- `expect`, what counts as a pass: `verdict` (answered / refused / chain), `must_cite` (each group
  needs ≥1 cited edge), `forbid_edges`, `yes_no`, `or_refused` (only dev-17/18; dev-19 expects a
  refusal), `or_excerpt_of` (an `s_` excerpt of that model satisfies `must_cite`), `modes_ok`,
  `downstream`, `no_direct_claim`;
- `source_lines`.

dev-10 ("does raw_payments.amt affect dim_customers.lifetime_value?") must be answered "no", and
a refusal fails it, because the answer is in `impact_downstream`'s result: lifetime_value is not in
amt's downstream set.

## How the dev report scores
Per question, from the final `Answer` and the run record:
- **verdict**: refused / clarification / chain (ambiguity mode) / answered, and whether it matches
  `expect` (a refusal counts only where `or_refused` or `verdict: refused`);
- **pass**: the verdict is right, every `must_cite` group is hit, no forbidden edge is cited, no
  "directly" claim where `no_direct_claim` is set, and the yes/no matches. The yes/no check is a
  regex on the first sentence of `answer_text`; it is a **heuristic** and is labelled so;
- **recall**: gold edges among the final cited edges / gold edges. Trace gold is the full upstream
  closure, so recall < 1 is normal for a short answer; it shows how much of the path is cited;
- **extra edges**: cited edges not in gold or `also_ok`;
- **validator outcome**: pass / repaired / completed / regenerated / warning / refused / n/a
  (refused or clarified before validation);
- first-draft failures by rule, LLM calls, max estimated input tokens, latency (cached runs are fast).

**R8 measurement** (the session-5 open question in validator.md): first-draft claims with an R8
failure, and how many are **completable**: every column the claim names is connected to the
first one by this question's ledger edges (undirected, any length; the ≤4-hop count is shown too).
The decision rule was fixed before the run: completable R8 drops ≥ 10% of all first-draft claims
→ build citation completion; otherwise do not.

## Why this is not the official metric
- `eval/metrics.py` is owner-written ([H]) for v0.3 and implements spec §11.4 (node-set P/R/F1, path
  exact match, hallucinated-node rate, bootstrap CIs). This script only answers "does v0.2 work on
  20 questions?", with simple pass rules chosen for that.
- 20 questions on a 15-model corpus have no statistical power, and the agent was tuned on them.
- The yes/no check is a regex, and the "directly" check is keyword-based.
- Recall is over cited edges only; it ignores prose, and it does not score nodes the way §11.4 does.

## Results (local qwen3:4b-instruct-2507-q4_K_M, 3 Oct 2026)
Raw reports: `eval/reports/dev_before.json` (no completion) and `eval/reports/dev_after.json`
(with R8c). Latency is from the uncached "before" run: 144.5 s for 20 questions (median 6.5 s). The "after" run was fully cached (69/69 calls).

| | before R8c | after R8c |
|---|---|---|
| verdict correct | 17/20 | 17/20 |
| pass | 15/20 | 16/20 |
| mean gold-edge recall (answered) | 0.62 | 0.72 |
| cited edges not in gold | 10 | 10 |
| validator outcomes | pass 6, repaired 5, regenerated 1, warning 3, refused 1, n/a 4 | pass 6, repaired 5, completed 4, refused 1, n/a 4 |
| first-draft claims raw / repaired / completed / failed | 28 / 5 / 0 / 4 | 28 / 5 / 4 / 0 |
| first-draft failures | R8 = 4, R4.hallucinated = 1 | R4.hallucinated = 1 |
| LLM calls (total) / max est. input tokens | 73 / 1,946 | 69 / 1,946 |

**R8 measurement:** 4 of 37 first-draft claims were R8 drops, all completable. That is 10.8%,
at or above the 10% threshold, so completion (R8c) was built. See validator.md, "Resolved
(session 5a)", including the margin note.

The 4 failures after R8c are agent and linker problems, not validator problems. They are for later
sessions (one checklist item per session):
- **dev-10** (yes/no "no"): the tool calls found no citable evidence, so code refused before
  the answer phase. The correct "no" needed `impact_downstream(raw_payments.amt)`.
- **dev-11** (how is revenue_finance computed): the model called `get_model_sql` with a column
  id as the model, got `unknown_model`, and stopped, so code refused. A tool-argument problem.
- **dev-15** (paraphrase "number of orders per customer"): the fuzzy v1 linker returned 5 mixed
  candidates, so the policy asks for clarification. This is linker v2 work (v0.3).
- **dev-20** (star + union trap): it cited the payments branch only and missed `refunded_at`.

Two passes are worth a look. dev-18 passed only as a refusal ("the evidence does not
explain…"), not by correcting the premise. dev-19 was refused by the validator (R4.hallucinated
on `stg_orders.ship_date` in the prose), not by code, because the linker tied 5 `order_date`
columns for "ship_date" and chain mode answered.

## Explain-back questions
1. Why must a dev question never appear in the frozen test set, and why is a different *target
   column* not enough on its own once the corpus grows (think: what else did the dev set tune)?
2. dev-10 refuses. Why is that scored as a fail, while the same refusal on dev-18 passes? Point to
   the field in `expect` that decides it.
3. A claim names `a.x` and `c.x` and cites only `b.x → c.x`; the ledger also has `a.x → b.x`. Is this
   R8 drop counted as completable? Would it still be if the only ledger path went through 5 edges,
   and which of the two counts does the 10% rule use?
