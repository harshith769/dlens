# Post-pilot fixes (design only, S13)

Status: **design, no code.** Written 21 Oct 2026, during the S13 pilot freeze. Every fix below
changes `src/dlens/agent/**`, so it changes `s4.agent_code_sha256()`. Nothing here runs before
the pilot table is committed and an approved plan names the fix (CLAUDE.md: validator rules
change only when the plan names them). F1–F4 come from `docs/plans/pilot-design.md` §4 and the
S13 prep audit (`eval/reports/s13/prep_audit.md`, qwen S4, dev). F5 is the transport-error gap
from the S4 Gemini run (pilot-design §3.1). F6 comes from the Ask scores (pilot-design §5).

Caveat on every audit number: "consistent" means the claim's dotted mentions are in the
question's gold set. It does not mean the stated relation was checked to be true.

## How each fix is checked without tuning on dev

The same rule for all five fixes:

1. **Dev cases become unit tests.** The audit's failing claims (ids and texts below) go into the
   validator / loop tests as fixtures: the dropped claim must pass after the fix, and a matching
   negative case must still fail. These tests pin the mechanism, not a score.
2. **No dev re-score loop.** Re-running dev and adjusting the fix until dev F1 rises is tuning on
   dev; it is not done. A single dev re-run after the fix is reported for information only.
3. **The honest check is the test set, after the 7 Dec 2026 freeze.** The fix is frozen together
   with the S4 system, and its effect is the test-set result. Nothing on test is looked at before
   that.
4. **Guard tests.** Each fix lists the existing guard it must not weaken (below), and the guard's
   current tests must still pass unchanged.

---

## F1. R8: a claim citing one edge of a multi-hop link

**Problem.** R8 dropped 11 claims; 10 were gold-consistent: dev-53 ×4, dev-65 ×4, dev-72 ×2.
They are impact claims such as "stg_product_costs.product_id affects
int_order_item_margins.product_id through a join", citing a single edge (`e_81158afd`) of a
longer path. Headline F1, raw → validated: dev-53 0.149 → 0.032, dev-65 0.903 → 0.741.

**What already exists.** R8c (path completion) adds the missing bridge edges from the question's
ledger, under three guards: an **anchor** (one cited edge touches a named column), a **shortest
directed path of ≤ 4 hops** (`MAX_COMPLETION_HOPS`), and the **"directly" guard**. These claims
were not completed, so one of the guards or the ledger stopped them. **Step 0 of F1 is a
read-only diagnosis** of each of the 10 claims: no anchor, a bridge longer than 4 hops, or a path
missing from the ledger. The option follows from that diagnosis; the doc is updated before any
code.

**Options.**
- (a) **Raise `MAX_COMPLETION_HOPS`** (e.g. to 6), if the diagnosis shows the bridges are 5–6
  hops. Smallest change; the path still comes from this question's ledger.
- (b) **Relax the anchor** to "a cited edge or a ledger edge touches a named column", if the
  diagnosis shows the anchor is the blocker. Weakens the R7 relevance guard; needs a careful
  negative test.
- (c) **Accept a ledger-connected claim without adding edges** (R8 passes when the ledger
  connects the columns). Simplest to state, but the cited ids then no longer show the path, so
  citation coverage means less.

**Recommendation.** Decide after step 0. Lean (a), because it keeps every guard and only widens a
bound; (c) is rejected unless (a) and (b) do not cover the cases.

**Files.** `src/dlens/agent/validator.py` (R8c: `MAX_COMPLETION_HOPS`, `_complete_one`),
`docs/explain/validator.md`. Rule-9 touch: **validator**.

**Tests.** The 4 dev-53 claims (with their ledger edges as a fixture) complete and pass. A
sibling pair that only shares a descendant stays unconnected (the existing R8c guard). A
"directly" claim over a multi-hop path still fails. A bridge longer than the new bound still
fails.

**Guard not weakened.** R7 (a cited edge touches a named column), the "directly" guard.

Decision: PENDING

---

## F2. R4: SQL table / CTE aliases in claim text

**Problem.** R4.hallucinated dropped 6 claims; 3 were consistent: dev-30 (`orders.order_date`,
`shipments.shipped_at`) and dev-46 ×2 (`orders.order_date`). The model wrote the SQL alias
(`{{ ref('fct_orders') }} as orders`) instead of the model name. M3's identifier filter ignores
the alias, but R4 calls it hallucinated. dev-46 ends "no verifiable claims" (clarify 1 → 0, a
false refusal).

**Options.**
- (a) **Skip alias tokens in R4.** Collect the aliases of the models in this question's ledger
  (CTE names, derived tables and `ref(...) as x` aliases) and treat `alias.column` as "not a node
  name" (neither hallucinated nor supported). Mirrors M7 (iv-k+) and `metrics.relation_names`,
  extended to ref aliases.
- (b) **Rewrite alias tokens** to the model they stand for (`orders.order_date` →
  `fct_orders.order_date`) before R4, then check normally. More useful text, but code would
  change the model's words, and one alias can name different models in different files.
- (c) **Prompt only:** tell the model to use model names, never SQL aliases. No validator
  change, but the freeze-relevant prompt hash changes, and it does not guarantee anything.

**Recommendation.** (a). Symmetry (rule 12): validator and metric treat the same token the same
way. (b) is rejected because an alias is not unique across files.

**Files.** `src/dlens/agent/validator.py` (R4), possibly a shared alias helper next to the
lineage SQL reader (read-only use of `src/dlens/lineage`; no lineage change),
`docs/explain/validator.md`. Rule-9 touch: **validator**.

**Tests.** dev-30 and dev-46 claim texts with their compiled SQL as fixtures: no R4 failure. A
truly unknown `foo.bar` (not an alias, not a node) still fails R4.hallucinated. An alias that is
also a real model name is checked as the model.

**Guard not weakened.** R4.hallucinated on real unknown identifiers.

Decision: PENDING

---

## F3. Regenerate fallback when the regenerated draft refuses

**Problem.** dev-75: the raw verdict was `no` (correct). The first draft failed validation, the
regenerated draft **refused** with `reach_verdict: null`, and the loop returned that refusal.
yes/no 1.0 → 0.833 (n = 6), one false refusal.

**Mechanism (from code).** `validate()` marks a refusal `passed=True, skipped=True`, so in
`loop._validate` a refused second draft counts as passing and is returned as is. The first
draft's passing claims are never considered.

**Options.**
- (a) **A refused second draft is not a pass.** If the first draft was not a refusal, a refused
  regenerate goes to salvage (best of first / second by kept claims) instead of being returned.
  Smallest change, and it reuses salvage, which already sets code's verdict from a reachability
  fact.
- (b) As (a), and also **keep the first draft's verdict** when salvage keeps claims but has no
  fact. More content kept, but a verdict without a verified claim is not "code guarantees".
- (c) **Prompt the regenerate** not to refuse when its failure list has passing claims. Does not
  guarantee anything; changes a prompt hash.

**Recommendation.** (a). Salvage exists to keep the best verified content; a regenerate exists to
fix failures, not to discard checked claims.

**Files.** `src/dlens/agent/loop.py` (`_validate`), `docs/explain/agent.md`. Rule-9 touch:
**loop** (no validator rule changes).

**Tests.** A fixture with dev-75's shape (first draft: one passing claim and a verdict; second
draft: refused) ends with the salvaged claim and a warning, not a refusal. A first draft that
was itself a refusal is unchanged. A regenerate that passes with claims is unchanged.

**Guard not weakened.** Salvage still drops every failing claim; a refusal with no passing
first-draft claim stays a refusal.

Decision: PENDING

---

## F4. The target claim lost to a truncated id

**Problem.** dev-16: the claim naming the question's target cited `e_81a3f`, a truncated edge
id. It failed R2, its rewrite failed R5, and salvage kept no claim naming the target. Chain
1.0 → 0.5 (n = 2), upstream F1 1.0 → 0.0.

**Mechanism (from code).** R2r repairs a miscopied id when it is unique and either one edit away
or a prefix of ≥ 7 hex characters (`MIN_PREFIX_HEX`). `e_81a3f` has 5, so it was not repaired.

**Options.**
- (a) **Lower `MIN_PREFIX_HEX` to 5** (still unique within this question's ledger, still same
  prefix). It fixes the cause, the id, and is a citation repair like the existing R2r.
- (b) **Target preservation in salvage:** if no kept claim names the target, keep the first
  draft's target claim when it failed only on R2. Content-level; keeps a claim whose citation is
  still broken.
- (c) Both.

**Recommendation.** (a). The answer stays about the question asked because its citation is
repaired, not because a broken citation is excused. With 5 hex characters (16⁵ ≈ 1M) a unique
match in one question's ledger (tens to hundreds of ids) is very unlikely to be a wrong match;
the uniqueness check stays.

**Files.** `src/dlens/agent/validator.py` (R2r: `MIN_PREFIX_HEX`), `docs/explain/validator.md`.
Rule-9 touch: **validator**.

**Tests.** dev-16's claim with a ledger containing the full id: repaired, then checked by R5 as
usual. Two ledger ids sharing the 5-hex prefix: not repaired (ambiguous). A 4-hex prefix: not
repaired.

**Guard not weakened.** R2 on an id that matches nothing or more than one ledger id.

Decision: PENDING

---

## F5. Transport errors from the Gemini adapter

**Problem.** The S4 Gemini pilot run crashed at dev-38 with `httpx.RemoteProtocolError`
("Server disconnected without sending a response") after the google-genai SDK's own retry gave
up (pilot-design §3.1). The Gemini adapter catches only `google.genai.errors.APIError`, so a
transport error is not a `ProviderError`. The loop's retry-once path handles only
`ProviderError`, and the exception stopped the runner instead of becoming one failed record.
The other adapters already map this: `openai_compat.py` catches `httpx.HTTPError`, and
`ollama.py` catches connection errors.

**Options.**
- (a) **Map httpx transport errors in the Gemini adapter** (`httpx.TransportError`: disconnects,
  timeouts, connect errors) to `ProviderError(retryable=True, status_code=None)`, like
  `openai_compat.py`. Smallest change, matches the other adapters.
- (b) **Map them once in `LLMClient`** for every provider. One place, but it duplicates what two
  adapters already do and blurs the adapter's job.
- (c) **Runner-level catch-all** per question in `eval/systems/s4.py` (any exception → an error
  record). Keeps a run going, but hides crash-class bugs that should stop a run.

**Recommendation.** (a). A dropped connection is a provider condition; the loop already knows
how to retry one. The exception text must keep the existing rule: no request object, so no key
(`from None`, as in `openai_compat.py`).

**Files.** `src/dlens/agent/llm/gemini.py`, `docs/explain/llm.md`. Rule-9 touch: none (no
validator or loop change), but it is under `src/dlens/agent`, so it **changes the agent-code
sha**: after the pilot. S1 also uses this adapter: `s1.frozen_hashes()` does not cover the
adapter (prompts, schema, budget rule only), so the B8 hashes stay equal; the S1 design change
log records the change anyway.

**Tests.** A stub client raising `httpx.RemoteProtocolError` → `ProviderError` with
`retryable=True`; the loop retries once and, on a second failure, writes a failed record and the
run continues. The exception text holds no key or request. An `APIError` 400 stays
non-retryable.

**Check.** Not a quality fix, so no score check: the unit tests above, and the next cloud run
completes or records the error per question.

Decision: PENDING

---

## F6. Ask refusals: S4 refuses "no lineage evidence" on meaning questions instead of calling search_docs

**Problem.** On qwen, S4 refused 5 of the 12 Ask (meaning) questions: dev-78, dev-82, dev-84,
dev-86 and dev-87. Ask means (AI-scored, pilot-design §5): S4 0.306 vs S1 0.660 on qwen, and S4
0.639 vs S1 0.729 on Gemini.

**Mechanism (from the records and code).** In each of the 5, the model's one tool-phase call
returned no tool call. `loop._answer_phase` then found no evidence item and refused with "no
lineage evidence was found for this question". search_docs was available (the run has an index)
but was never called. Gemini's single Ask refusal (dev-87) is a different case: it called
search_docs and get_model_sql, and the validator refused ("no verifiable claims"). F6 targets the
qwen pattern only.

**Caveat.** n = 12, and the scores are AI-scored (Claude, owner-authorised, not owner
hand-scored). The refusal count does not depend on the scorer: a refusal scores 0 under the
header rule whoever scores. The size of the gap does depend on the scorer.

**Options.**
- (a) **Code runs search_docs before refusing.** When the tool phase ends with no lineage
  evidence and an index exists, code calls `search_docs` with the question (a code step, like
  chain mode's code tool calls), and the answer phase runs on the hits. It is deterministic,
  and "code guarantees" holds, because the hits are tool results the validator checks like any
  other (R2/R3 on `c_` ids). Chunk-only lineage claims still fail R8 (S12b B4 owner decision).
  The risk is refusal accuracy: an unanswerable question could now get a docs-based answer.
  Guard: unanswerable questions must still refuse, through the existing unknown-column and
  out-of-domain checks or a minimum hit score.
- (b) **A prompt nudge only** ("for meaning or definition questions, call search_docs"). It is
  the smallest change, but it guarantees nothing on a 4B model (the model already ignored an
  available tool), and it changes the answer-phase prompt hash.
- (c) **Intent routing for meaning questions.** Code classifies the question (Ask / meaning vs
  lineage) and calls search_docs up front for meaning questions. It helps beyond refusals, but it
  needs a classifier, which is a new component with its own errors, and it overlaps with the
  linker's job.

**Recommendation.** (a). It turns a code-made refusal into a code-made tool call, at the exact
point where the refusal happens today, and it needs no classifier. (c) can follow if (a) shows
the model still under-uses docs once it has hits.

**Files.** `src/dlens/agent/loop.py` (`_answer_phase` and the tool phase's end),
`docs/explain/agent.md`. Rule-9 touch: **loop** (no validator rule change).

**Tests.**
- Stub model making no tool call on a meaning question, with an index: code calls search_docs
  (a `code` step), and the answer phase runs on its hits.
- The same without an index: the refusal is unchanged.
- An unanswerable fixture (dev-89-style unknown column, and an out-of-domain question): it still
  refuses.
- A lineage question with evidence: search_docs is not called.

**Check.** The 5 qwen dev cases become unit fixtures (the stubbed model output from their
records). No dev re-score loop. The honest check is Ask and refusal accuracy on test after the
7 Dec 2026 freeze, scored on a blind sheet.

Decision: PENDING

---

## Change log

- 21 Oct 2026 (S13): v0.1. F1–F4 from pilot-design §4 and the prep audit, F5 from the S4 Gemini
  run. Design only; every decision pending; no code.
- 22 Oct 2026 (S13 follow-up): F6 Ask refusals (qwen 5/12, "no lineage evidence", search_docs
  never called). Design only; decision pending.
