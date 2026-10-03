# Explain: validator (`src/dlens/agent/validator.py`), interface only

**Status: stub.** The rules are [H], written by the owner in session 4 (spec §14). This page
documents the interface the agent loop already calls, so session 4 only fills in the rules.

## What it does (now)
`validate(answer: Answer, ledger: Ledger) -> ValidationResult(passed, failures, cleaned_answer,
stub)`. `Ledger` is a Protocol with `emitted_ids` and `record(id)`; `Toolbox` satisfies it. The
stub returns `passed=True`, no failures, the answer unchanged, and `stub=True`. The run record
and the CLI trace line show `validator: stub`, so no answer is mistaken for a validated one.

`ValidationFailure {claim_index, rule, item_id, message}` names the claim (or `None` for the whole
answer), the spec §8 rule number and the offending id.

## Where it plugs in
In `loop.py`, after `attach()` (citations from the ledger) and before the answer is returned. A
clearly marked `REGENERATE ONCE` block sits right after the call: on failure, drop the failing
claims, re-run the answer call once with the failures listed, and if that fails again return
with a warning flag. The 8-call budget already reserves that call.

## Rules to implement (spec §8)
1. Every claim cites at least one edge or chunk id.
2. Every cited id appears in a tool result from this conversation (`ledger.emitted_ids`).
3. Every cited file and line range exists on disk and contains the column (`star` level:
   contains `*`; `s_` excerpts: file and range exist; see tools.md).
4. On failure, drop the claim and regenerate once; if it fails again, warn.

## Planned rules for session 4 (beyond spec §8)
These are documented only, not implemented yet.
- **Hallucinated-node check.** Every model or column identifier mentioned in `answer_text` or in
  a claim's text (e.g. `fct_orders.revenue_finance`, `stg_refunds`) must appear in this
  question's evidence: an emitted edge's endpoints, an excerpt's model, or a context line
  (impact models and exposures, resolve candidates). An unknown identifier fails the claim (or
  the answer text). This catches a correct-looking id list attached to prose about a node no tool
  returned.
- **Unsupported sentences.** Each `answer_text` sentence that no claim supports is flagged:
  matched by the identifiers it mentions against the claims' texts and cited edges. The answer
  text is a summary of claims, so a sentence with no claim behind it is uncited narration.

## What it must not use
`confidence` is the model's self-report. It is never an input to validation or to benchmark
scoring.

## Why this design
- The interface is fixed before the rules, so the loop, the run log and the no-validator
  ablation (which reads `draft_raw` and `validation` from the run records) are already wired.
- A pass-through stub that labels itself is honest: v0.2 smoke runs show what the raw model
  does. Questions b and c cited miscopied ids (`e_4b2_403a`, `s_b3ece5f`), which rule 2 will
  catch; the live smoke check `all_cited_in_ledger` is the test session 4 must turn green.

## Alternatives rejected
- Validating inside the LLM prompt ("only cite ids you saw"): it is already in the prompt, and a
  4B model still miscopied an id.
- Constraining ids with a JSON-schema `enum` of ledger ids: it would hide exactly the failures
  the no-validator ablation is meant to measure. It is listed as a v0.3 ablation candidate
  instead (spec §11.5: validator only / constrained only / both).

## Explain-back questions
1. Why does `validate` take the ledger instead of reading the files and ids itself, and what
   does that make easy to test?
2. Rule 2 and the citation lookup in `attach()` both consult the ledger. What does each one
   guarantee, and why is `attach()` alone not enough?
3. Why must `confidence` never feed the validator or the scoring, even when it correlates with
   correctness on the dev set?
