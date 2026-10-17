# Entity linker v2 (`resolve_entity`, S08)

Code: `src/dlens/agent/tools/entity.py`. Design (owner-approved, with amendments A–E):
`docs/plans/linker-design.md`. Interface: ADR 0022. Measured: `eval/reports/linker.md`.

## What it does
Turns the words a user (or the model) used for a column, such as "number of orders per
customer", `stg_payments.amt` or "lifetime value", into ranked candidate columns and models. It
also says whether the result is **ambiguous** and whether **nothing** matched. The agent loop
acts on those two flags in code: the ambiguity policy, the unknown-column refusal and the
`linked_evidence` rule (agent.md).

## How it works
**Stage 1, exact (always ranked first).** A full id, a `model.column` id or a model name scores
1.00. A literal column name scores 0.97, and every column with that name gets it, so same-name
columns tie and come out ambiguous.

**Dotted ids (amendment C).** For `model.column` where the model exists, the column is exact, or
it maps through the **abbreviation table alone** (plus the weak `usd` rule) to columns of that
model: exactly one resolves, with the note "interpreted …"; two or more are ambiguous. Anything
else is no-match. There is no plural, fuzzy, typo, phrase or hybrid rescue. The agent loop's
refusal uses the same function (`dotted_column`), so the loop and the linker cannot disagree. When
the loop accepts an interpretation, code writes "Interpreted X as Y." at the front of the answer.

**Stage 2, normalised.** The text and every column name are split on case, separators and
camelCase:
- `surface` (0.93): the same tokens.
- `rewritten` (0.87): the same tokens after rewrites: plural (A), the abbreviation table (18
  entries, design §2.1), phrase rules (P1 "number of X", P2 "how many X", P3 "count of X" → `X
  count`; P4 "total X" → `X total`), dropping `usd`, and word order. A phrase rule adds a
  reading of the text and never removes the original one.
- `fuzzy` (≤ 0.80): bounded soft-Dice token overlap (each name token used once: the v1 >1.0 bug
  is gone) at 0.7, plus `difflib` character ratio at 0.3.

Then two adjustments:
- **Model bonus** (+0.06 × coverage): text tokens that name the column's model (layer prefixes
  excluded, B) and are not part of the column name become context. Full coverage can break a
  tie (0.06 > δ); partial coverage only orders candidates. Amendment D: no bonus at all when some
  column already matches the whole text ("payment method").
- **Layer prior**: marts +0.010, intermediate +0.005, staging 0, raw/seed −0.005. The spread is
  0.015 < δ, so it orders ties but never resolves them.

**Stage 3, hybrid** (only with a built S07 index, and only when stage 2 has no surface or
rewritten match): the S07 hybrid search over column cards. A card counts only if its dense
cosine is ≥ 0.80 (RRF ranks are relative, so rank 1 exists even for junk). Its score is 0.50 +
0.30 × rrf_norm, ranked together with the stage-2 fuzzy candidates. Without an index the payload
says `"hybrid": "unavailable"`, which is always the case in the core and demo installs.

**Decisions.** Nothing below τ = 0.60 is a candidate (`candidates: []`; the below-threshold
`closest` ids go to the side record only, never to the LLM). `ambiguous` = top1 − top2 < δ =
0.05 on the raw sums; printed stage-2/3 scores are capped at 0.96 (E). Score parts (stage, tier,
base, model bonus, layer, rules, hybrid ranks and cosine) are in the side record.

## Why this design
- **Stages, not one blended score.** In v1 an exact id could lose to a fuzzy model name (three
  ids in linker_gaps.yml). Ranking stage 1 lexicographically makes that impossible, whatever the
  weights are.
- **Tiers spaced against δ.** surface vs rewritten is 0.06 > δ, so "lifetime value" prefers
  `lifetime_value` over `lifetime_value_usd` without calling it ambiguous, while two columns with
  the same evidence stay ambiguous and go to the loop's chain/per-candidate policy (dev-16).
- **Weights by reasoning, not fitting.** With 20 dev questions (3 description-worded), fitting
  would memorise them. Each weight is argued against δ in the design doc. Re-checking happens
  on dev only, after S09.
- **Thresholds as decisions.** v1 returned everything ≥ 0.30, so the agent could never be told
  "no such column". τ makes no-match a result: 14/15 linker-dev and 19/20 linker-test no-match
  cases, against 2/15 and 3/20 for v1.
- **Hybrid is a cascade.** Identifier-worded text never pays for an embedding, and its
  candidates are the same with or without the retrieval extra (only the `hybrid` key differs), so
  the demo, which has no index, ranks exactly as dev runs do.

## What it costs (measured, eval/reports/linker.md)
Description-worded mentions got **worse** than v1 (linker-test top-1 0.30 → 0.17 without hybrid,
0.22 with). v1 returned low fuzzy candidates with no threshold, and τ removes them. Gold-card
cosines are mostly 0.60–0.82, so COS_MIN = 0.80 admits few cards. The design's change rule (more
than 10% of linker-dev no-match cases misclassified) did not trigger for τ (1/15) or COS_MIN (0),
so both stand; the trade-off is the owner's decision. Other known limits: "per day" does not match
the model token "daily" (no stemming); a layer token in the text ("raw") is ignored, not used;
the layer prior reads name prefixes, so dbt_jira's `jira__*` marts get no marts bonus.

## Alternatives rejected
- **A fitted scorer** (logistic regression on features): too few labels, and it would tune
  toward the set we report on.
- **Always running hybrid and fusing it:** demo payloads would differ from dev payloads, and
  exact-looking queries would pay for an embedding.
- **A reranker / cross-encoder:** a new model and dependency, for failures that are lexical or
  caused by missing card text (dev-15's card has no description).
- **`number → count` as a plain token rewrite:** "order number" is not a count.
- **Letting the LLM pick among candidates:** the code decides; the LLM narrates.

## Explain-back questions
1. "dim_customer_segments.customer_segment" ranked 4th in v1 although it is an exact id. Name
   the v1 bug that caused it, and the two separate v2 mechanisms that each prevent it on their
   own.
2. Walk "number of orders per customer" through v2: which readings of the text exist, which
   tokens become model context for `dim_customers` and why not for `fct_daily_revenue`, the score
   parts of the winner, and why the result is not ambiguous. What would change if the text were
   "number of orders per day"?
3. `stg_payments.amt` is answered but `fct_orders.revnue_finance` is refused before any LLM
   call. Which single function decides both, what exactly may it rescue, and what does the user
   see in the answer for the first one?
