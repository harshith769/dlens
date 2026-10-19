# Metrics design (S10, v0.3 D3)

**Metrics-design version:** 1.0-draft (becomes 1.0 when every Decision below is set). Every scored
report names this version and `eval/metrics.py`'s `__version__`.
**Status:** draft, 19 Oct 2026. **Every definition is the owner's decision.** `eval/metrics.py` is
not written until every `Decision:` line below is set.
**Inputs:** spec §8 (answer schema, validator, S4 views) and §11.2–11.5;
`docs/plans/v0.3-plan.md` D2–D4; `docs/plans/questions-design.md` §1, §5, §7;
`eval/questions/dev.jsonl` (96); `dlens.gold_spec`; the run-record format (`RunRecord`,
`src/dlens/agent/runlog.py`).

Rules that hold throughout:
- Gold comes only from `dev.jsonl`, which `dlens.gold_spec` computed from `lineage_spec.yml` (plus
  `traps.yml` for exposures). Metrics never grade a system with the system's own engine:
  `eval/metrics.py` imports `dlens.gold_spec` and the standard library only, never
  `dlens.lineage`, `dlens.agent`, `dlens.retrieval` or `dlens.graph`.
- This document holds no measured result of S1 or S4. Worked examples show question text and gold
  only. "Consequence" paragraphs state structural facts about the systems, never their scores.
- The primary scoring mode of a question is chosen from its wording, never from what any system
  does (hard rule 5).
- The answer schema is not changed in S10. Fields that a definition needs and that do not exist
  yet are listed as S11 / S12 requirements (§18).

---

## 0. What exists today (inventory)

**Answer fields today** (`Answer`, spec §8): `answer_text`, `claims[{text, edge_ids, chunk_ids}]`,
`subgraph`, `confidence` (never scored), `refused`, `refusal_reason`, `clarification{question,
candidates}`, `partial_evidence`, `citations{id → {file, line_start, line_end, level:
line | star | model}}`, `validation_warning`.

**Planned for S12 and not present today:** `premise_corrected`, claim `origin` (`model`,
`repaired`, `completed`, `augmented`), a structured yes/no verdict, a structured "uncovered part"
for multi-part questions, a structured interpretation. Today an interpretation exists only as the
code-written lead sentence "Interpreted A as B." at the start of `answer_text`.

**Run record** (one JSON line per question): question text (no question id), provider, model,
params, the tool steps with each result's payload and side records (`edges`: edge id → from, to,
kind, citation; `facts`: `r_` reachability facts), `ambiguity{mode, candidates, downstream}`,
`draft` (the parsed pre-validation answer = S4-raw), `regenerate_draft_raw`, `clarification`,
`validation{first, second, repairs, completions, dropped_claims, failures, warning}`,
`final_answer` (S4-validated), `stop_reason`, `error`, `timings{total_ms, …}`,
`tokens{llm_calls, sum_input, sum_output, max_est_input, cached_calls}`. No run-manifest file
exists yet.

**Structural facts about the systems:**
- S4's `trace_upstream` and `impact_downstream` traverse direct edges only today; the R9 `r_`
  reachability fact is a direct-edge check. S4 therefore cannot state an indirect-only dependency
  from its tools today.
- S4's tools default to `max_depth = 10`. The deepest dev target is at hop depth 9. No dev gold
  closure needs more than 10 hops (breadth-first): the largest is 9 hops in direct mode and 10 in
  direct + indirect mode (dev-46, dev-47).
- S1 (built in S11) uses the same answer schema, has no validator and cites chunks, not edges.

**Gold fields in dev.jsonl (96):** verdicts answered 81, refused 9, partial 3, chain 2, clarify 1.
`upstream`, `sources` and `paths` exist on 30 questions (upstream 24, ambiguous 3, multi-part 3);
computed (11) and false-premise (4) questions have `inputs` only. Every `paths` list has exactly
one path. The false-premise shape is `premise{edge{from, to}, direct_edge, reaches_all, path?}`.
`interpretation` is on 0 dev questions; `closest` on the 9 unanswerable; `focus: exposures` on
dev-64. Gold differs between direct and direct + indirect on 50 questions.

**Worked examples (gold only):**

| id | question | direct | direct + indirect |
|---|---|---|---|
| dev-70 | Which columns are downstream of dim_customer_segments.customer_id in the lineage? | 0 columns, 0 models | 9 columns, 2 models |
| dev-71 | What depends on customer_id in int_customer_sessions? | 0 columns | 21 columns, 4 models |
| dev-72 | Is dim_customer_segments.rfm_score downstream of int_order_financials.items_subtotal in the lineage? | yes (5 hops) | yes |
| dev-73 | Would a change to raw_payments.created_at show up in fct_payment_events.event_at? | yes (3 hops) | yes |
| dev-74 | If int_product_costs_current.product_id changes, does it affect int_order_item_margins.line_margin? | **no** | **yes** (1 indirect hop) |
| dev-75 | Is customer segment in customer leaderboard downstream of last name in raw customers in the lineage? | no | no |
| dev-09 | Which columns are affected if int_order_financials.order_date changes? | 24 columns, 13 models, 1 exposure | 62 columns, 15 models, 2 exposures |
| dev-52 / 53 / 60 | impact questions | 0 exposures | 1 exposure |
| dev-03 | Where does int_order_items_enriched.line_amount come from? | upstream 4 | upstream 8 |

---

## M1. Scoring table: which gold field, which metric, which mode

**Question.** For each question type and subtype, which gold field is the answer key, which
metric scores it, and in which mode (mode rule: M4)?

**Options for trace / upstream (the main open choice):**
- (a) **Upstream closure** (`gold.upstream`): every column the target derives from, seeds included.
- (b) **Sources** (`gold.sources`): only the seed columns at the end of the chains.
- (c) **Inputs** (`gold.inputs`): only the one-hop inputs.

**Options for impact:**
- (a) **Columns, models and exposures scored separately**, columns as the headline.
- (b) One combined set (columns ∪ models ∪ exposures).

**Recommendation.** Trace upstream: (a) closure F1 as the headline, with sources-F1 and inputs-F1
as diagnostics. "Where does X come from?" asks for the whole chain; sources alone would reward
skipping every hop, and inputs alone would reward stopping after one. Impact: (a) separately; a
combined set lets 60 columns drown 2 dashboards.

| Type / subtype | n | Gold field | Headline metric | Diagnostics |
|---|---|---|---|---|
| trace / upstream | 24 | `upstream[mode]` | node-set F1 | sources F1, inputs F1, path node coverage (M6) |
| trace / computed | 11 | `inputs.direct` (+ indirect `from`s in all mode) | node-set F1 | — |
| trace / ambiguous | 3 | `verdict`, `candidates`, `upstream` | verdict correct (M9); chain: upstream F1 of the gold target | candidate recall |
| trace / multi-part | 3 | `upstream`, `out_of_scope` | upstream F1 (as upstream) | uncovered part named (M10, after G2) |
| trace / false premise | 4 | `inputs`, `premise` | inputs F1 + premise rejection (M10) | silent / asserted counts |
| impact / downstream | 24 | `downstream[mode]`, `models[mode]`, `exposures[mode]` | columns F1 (dev-64, `focus: exposures`: exposures F1) | models F1, exposures F1 |
| impact / yes-no | 6 | `reach[mode]` | verdict accuracy (M5) | heuristic prose verdict (labelled) |
| ask / meaning | 12 | `facts` | hand rubric (M11) | — |
| unanswerable | 9 | `verdict: refused` | refusal correct (M9) | `closest` named (not scored) |
| interpreted near-miss | 0 in dev | `interpretation` | M9 rule, then scored as its underlying type | — |

**Dev examples.** dev-03 (upstream 4 direct; sources 2; inputs 2). dev-09 (24 / 13 / 1 direct).
dev-64 ("Which dashboards are affected…", exposures headline).

**Consequence.** S0 is exact on every field it can compute (M14). S1 and S4 are scored on the same
fields through the same extractor (M3). Ask is outside every automatic number.

`Decision: PENDING`

---

## M2. Node identity and normalisation

**Question.** When is a predicted node "the same" as a gold node?

**Options.**
- (a) Short id `model.column`, compared case-insensitively, quotes stripped; fully-qualified ids
  (`model.<project>.x.y`, `seed.<project>.x.y`) cut to their last two parts. Seed columns are
  ordinary nodes. Models are compared by bare name in their own set; exposures by name in their
  own set. The question's own target is never part of its gold or predicted sets.
- (b) As (a), but models and exposures join the column set.

**Recommendation.** (a). The gold sets already exclude the target, include seeds and keep models
and exposures apart (dev.jsonl). Mixing levels (b) would let "fct_orders" count like a column.

**Dev examples.** dev-01: gold upstream `[raw_payments.amt]` (a seed column). dev-07: models
`[fct_inventory_status, int_inventory_daily, int_order_item_margins, int_order_items_enriched]`.

**Consequence.** Structural only: S4 records carry fully-qualified ids in side records and short
ids in prose; both normalise to the same key.

`Decision: PENDING`

---

## M3. Prediction extraction

**Question.** How does an answer become a predicted node set, a verdict and a refusal, the same way
for every system?

**Architecture (proposed).** metrics.py builds one internal **Prediction** per answer through
**one adapter per record format**: S0 and S4 now, S1 in S11. A Prediction holds: the answer
kind (answered / refused / clarification / chain / missing / crashed), the extracted mentions
(each with its negation flag), the structured verdict (M5), citations (M7), and the structured
diagnostics (cited-edge endpoints, where the format has them). Every scorer reads Predictions only.

**Options for the headline node sets.**
- (a) **Prose mentions**, one extractor applied identically to S0, S1 and S4: the text of
  `answer_text` plus every claim's `text`. S0 renders templated prose, so it passes through the
  same extractor.
- (b) **Structured**: endpoints of cited edges (S0 and S4 only; S1 cites chunks, not edges).
- (c) Union of (a) and (b).

**Recommendation.** (a) for every headline number, because it is the only extractor that applies
to S1 and S4 identically. (b) is reported as a labelled diagnostic for S0 and S4 only.

**Mention rules (for (a)).**
1. **Dotted ids.** Tokens of the form `name.name` (also the 3–4 part fully-qualified form, cut per
   M2), letters/digits/underscore, first character a letter or underscore. Tokens ending in a
   file extension (`.sql`, `.yml`, `.yaml`, `.csv`, `.py`, `.md`, `.json`) are not mentions.
   A dotted id counts toward a node set if it is in the gold inventory (M8); otherwise it is a
   hallucination candidate (M8).
2. **Bare names.** Two options, owner decides:
   - (i) **never counted** (recommended): `order_date` alone exists in many models; counting it
     guesses which one the system meant;
   - (ii) **counted if unique in the gold inventory** (exactly one `model.column` has that column
     name).
   Bare **model** names (for the models set) and **exposure** names (`finance_dashboard`, or the
   same words with spaces) are always counted: they are unique by construction.
   Predicted models = models of the non-negated column mentions ∪ non-negated bare model names.
3. **Interpreted names.** In a code-written lead "Interpreted A as B.", B counts and A does not.
4. **Negated mentions.** A negated mention is removed from every predicted node set (it still
   counts for M8 and M10).
   - *Clause*: text between sentence ends (`.` `!` `?` `;`) and the connectives "but", "however",
     "whereas", "while", "instead" (a comma before them is part of the boundary). A leading answer
     particle "Yes," / "No," is removed before the analysis.
   - *Cue*: inside the clause and **before** the mention: "not", "n't", "no", "never", "without",
     "rather than", "instead of", "except", "excluding", "other than", "neither", "nor",
     "no longer". The two-word phrase "not only" is **not** a cue.
   - Every cue word is matched as a whole word, case-insensitive.
   - The fixed sentence list in Appendix B is the test of this rule (≥ 15 sentences with the
     expected result for each). Each report shows, per system, how many mentions the rule removed.
5. **Views.** S4-raw = the record's `draft` (pre-validation). S4-validated = `final_answer`.
   S4-augmented = S4-validated plus the claims with `origin: augmented`. Until S12 adds `origin`,
   S4-augmented equals S4-validated and the report says so.

**Dev examples.** dev-17 "Why does fct_orders.revenue_finance include
int_customer_order_history.sales_tax?" — an answer "It does not include
int_customer_order_history.sales_tax; it uses …items_subtotal and …refund_amount" yields the
prediction {items_subtotal, refund_amount} with sales_tax as a negated mention (M10: rejected).

**Consequence.** S0 writes ids in prose by construction. S4's answer phase already writes
`model.column` ids. **S11 requirement:** the S1 prompt asks for `model.column` identifiers exactly
as S4's prompt does, so the shared extractor treats both the same.

`Decision: PENDING` (rules 1–5, and bare names (i) or (ii))

---

## M4. Direct vs direct + indirect

**Question.** Gold stores both modes wherever they differ (50 dev questions). Which mode is the
headline for each question?

Indirect pair identity: a pair is (from, to) with the **set** of indirect types it carries (JOIN,
FILTER, …). Node-set metrics use the node at the far end; the types matter only to diagnostics.
Every set metric is computed and stored in **both** modes, whatever the option below.

**Options.**
- (a) **A wording rule picks one primary mode per question** (the other mode is reported beside
  it). The rule:
  - *Provenance cues* → **direct**: "come(s) from", "computed", "calculated", "derived",
    "origin(ally)", "source".
  - *Effect / dependency cues* → **direct + indirect**: "affect(s/ed)", "change(s/d)",
    "impact", "show up", "depend(s) on", "downstream", "in the lineage", "feed(s) into".
  - **No cue, or cues of both classes:** the question's family decides: trace family (upstream,
    computed, ambiguous, multi-part, false premise) → direct; impact family (downstream, yes/no)
    → direct + indirect. The family is fixed when the question is generated, never by a system.
  - Why: a change to a join key or a filter column changes which rows reach the output, so "what
    is affected" includes indirect dependents (the perturbation oracle found 867 changes reachable
    only through indirect edges); "where does the value come from" asks for value provenance.
- (b) Direct everywhere is primary.
- (c) Direct + indirect everywhere is primary.
- (d) **Both modes reported, no primary**: every table has two columns and no single headline.

**Recommendation.** (a). It matches what a user asking each question needs, and Appendix A shows
the mapping for all 96 questions, so the owner approves the mapping, not just the rule. Under (a),
every trace-family question is direct and every impact-family question is direct + indirect;
no dev question's cues contradict its family except the false-premise wording "include" /
"depend on" (dev-17, 49, 50), whose premise holds in neither mode.

**Dev examples.** dev-70 / dev-71: direct gold is empty; under (a) they are scored on 9 / 21
columns. dev-74: direct "no", all "yes"; under (a) the correct verdict is "yes". dev-03: upstream
4 (direct, primary under (a)) vs 8.

**Consequence.** Structural: S4's tools are direct-only today, so under (a) or (c) S4 cannot reach
indirect-only gold until its tools traverse indirect edges (S12 requirement, §18). S0 computes
both modes. S1 has no mode; it is scored on the same primary set.

`Decision: PENDING` (and approve Appendix A)

---

## M5. Yes/no verdicts

**Question.** How is a yes/no answer read and scored?

**Today.** No structured verdict exists in the answer schema. The only verdicts are the prose of
`answer_text` and, for S4, the `r_` reachability fact (direct-only, S4-specific).

**Options.**
- (a) **Structured verdict only.** One accessor reads a structured field with values
  `yes | no | null`. A missing or null field on a yes/no question is scored wrong. The
  first-sentence prose heuristic is reported as a labelled diagnostic only.
- (b) Structured verdict when present, else the prose heuristic.
- (c) Prose heuristic for everyone.

**Recommendation.** (a). A heuristic over prose scores phrasing, not correctness: dev-72 and
dev-73 are worded "Is … downstream of …?" and "Would a change … show up …?", and a correct answer
to either can start with a sentence the heuristic cannot read. Mixing (b) would let one system be
scored by a parser and another by a field.

**The field.** Name `reach_verdict`, values `yes | no | null`, set only on yes/no questions.
- **S11 requirement:** S1 emits `reach_verdict` in the same answer schema.
- **S12 requirement:** S4 emits `reach_verdict` (additive answer-schema field, ADR), both before
  S13 (the pilot).
- **In S10, no answer-schema change:** S0 writes its verdict in an additive **record-level** key
  (`structured.reach_verdict`) of its run record. The accessor reads the record-level key now and
  the S12 answer field later; one accessor, one rule.
- Mode: the primary mode from M4 (dev-74 under (a): "yes").

**Consequence.** S0 is scoreable on yes/no in S10. S4's existing records have no field: their
yes/no rows are "not scorable (no structured verdict, S12)", with the heuristic as a labelled
diagnostic.

`Decision: PENDING`

---

## M6. Path node coverage (formerly "path exact match")

**Question.** What does the path metric measure, and what binary does McNemar use?

**Options for the path metric.**
- (a) **Path node coverage** (order-free): 1 if every node of some gold path (gold `paths` may
  list several; each dev list has one) is a non-negated mention, else 0. Computable for every
  system.
- (b) **Ordered path exact match**: the cited edges contain a chain equal to a gold path, in
  order. Needs cited edges, so S0 and S4 only.

**Recommendation.** (a) as the reported metric under the name "path node coverage"; (b) as an
S0/S4 diagnostic. §11.4's "path exact match" is renamed (spec change, §17).

**McNemar binary (S1 vs S4).**
- (a) **Question fully correct**: headline F1 = 1.0 (trace, impact), or verdict correct
  (yes/no, refusal, ambiguity verdict). Same definition for every system.
- (b) Path node coverage = 1 (trace questions only).

**Recommendation.** (a): it covers every automatically scored question and needs nothing S1 lacks.

**Dev examples.** dev-72 path: items_subtotal → … → dim_customer_segments.rfm_score (6 nodes).
dev-01 path: raw_payments.amt → stg_payments.amount_usd.

**Consequence.** Structural: S1 can be scored on (a) both times.

`Decision: PENDING`

---

## M7. Citation validity

**Question.** When is a citation valid, and how is validity reported?

**Check (independent, on disk; metrics.py never imports the validator).** For each citation in an
answer's `citations`:
1. the file exists under the corpus project directory (the path is resolved and must stay inside
   it);
2. `1 ≤ line_start ≤ line_end ≤` the file's line count;
3. the cited lines contain the **required column**, matched as a whole word, case-insensitive:
   - edge citation (`e_`), options: (i) the edge's `to` column (recommended: an edge citation
     points at the line that writes the output column); (ii) its `from` column; (iii) either;
   - `star` level: the lines contain `*`;
   - excerpt citation (`s_`, and S1 chunk citations): range in bounds and the lines contain at
     least one column the claim names;
4. `model` level (a whole file) is **invalid**. Within the invalid ones, a separate bucket counts
   those whose file contains Jinja (`{{` or `{%`) and none of whose lines name the column: the
   "macro-generated" bucket (relevant to set E).
5. `r_` facts are graph checks, not file citations: excluded from the denominator and counted
   separately.

**Reported.**
- **Per citation (micro):** valid / all checked citations.
- **Per answer:** over every **answered** answer (not refused, not a clarification), the answer is
  valid if every citation is valid. An answered answer with **zero citations is invalid**.
- **Citation coverage:** share of claims with ≥ 1 citation.
- **Disagreement with R3:** the count of citations where this re-check and the validator's R3
  outcome (read from the record's `validation` failures, no import) disagree, listed.

**Options for the per-answer rule.** (a) as above (recommended); (b) answers with zero citations
excluded instead of invalid.

**Dev example.** dev-01's gold edge raw_payments.amt → stg_payments.amount_usd: a citation of
`models/staging/stg_payments.sql` must contain `amount_usd` on its lines under (i).

**Consequence.** S4-validated passed R3 by construction, so disagreements there are expected to be
few and each one is listed. S1 has no validator; the same check applies.

`Decision: PENDING` (required column (i)/(ii)/(iii); per-answer rule (a)/(b))

---

## M8. Hallucinated-node rate

**Question.** What counts as a hallucinated node?

**Definition (proposed).**
- **Inventory:** the gold spec, not the graph: the 391 columns of `lineage_spec.yml` (318 model +
  73 seed), its 49 model and 14 seed names, and the exposures in `traps.yml` (`finance_dashboard`,
  `marketing_dashboard`).
- **Numerator:** distinct dotted mentions (negated or not) not in the inventory, excluding every id
  the question text itself writes (an unanswerable question's non-existent id echoed in a refusal
  is not a hallucination).
- **Denominator:** distinct dotted mentions in the answer.
- **Aggregation:** per answer, then macro mean over answers with ≥ 1 dotted mention; also the share
  of answered answers with ≥ 1 hallucinated node.

**Options.** (a) as above (recommended); (b) negated mentions excluded from both counts.

**Dev examples.** dev-92 "Where does fct_daily_revenue.revnue_finance come from?" — a refusal
naming `fct_daily_revenue.revnue_finance` is not a hallucination; one naming
`fct_daily_revenue.revenue_net` is.

**Consequence.** Structural: S4's R4 rule already rejects some of these in validated answers; S4-raw
and S1 have no such filter.

`Decision: PENDING`

---

## M9. Refusal, ambiguity and interpretation verdicts

**Question.** How are refusals, clarifications, chains and interpretations scored?

**Proposed rules.**
- **Refusal accuracy:** on the 9 unanswerable questions, the share refused. A clarification on an
  unanswerable question is not a refusal (wrong).
- **False-refusal rate:** on answerable questions (gold verdict answered, chain, partial or
  clarify), the share refused. dev-17's legacy `or_refused` is **not** honoured in the headline.
- **Chain** (dev-16, dev-31): correct if the answer is answered for the gold `target` (the most
  downstream candidate): the record's ambiguity mode is `chain` with downstream = target, or the
  target is a non-negated mention. Then scored as upstream.
- **Clarify** (dev-46): correct if a clarification is returned whose candidates ⊇ gold
  `candidates`. A full answer instead is wrong for the verdict.
- **Interpreted near-miss:** correct only if `answer_text` begins with "Interpreted A as B." and
  B = `gold.interpretation.column`; then scored as its underlying type. (0 such dev questions.)
- **`closest`:** not scored. Options: (a) not scored, reported as a diagnostic (share of refusals
  naming any gold `closest` name) (recommended: gold `closest` is edit distance on bare names and
  repeats names, e.g. dev-93); (b) scored as recall.

**Dev examples.** dev-19 "What is affected if stg_orders.ship_date changes?" → refused.
dev-46 "Where does order month come from?" → clarify, candidates fct_customer_cohorts.order_month,
fct_segment_monthly.order_month.

**Consequence.** S0-gold refuses unanswerable questions trivially (its target does not exist);
S0-linked refuses only on a linker no-match.

`Decision: PENDING`

---

## M10. False premise and multi-part

**Question.** How are false-premise and multi-part questions scored while `premise_corrected`
and the G2 field do not exist yet?

**False premise (4 questions).** The inputs set is scored as computed (M1). The premise is put in
one of three buckets:
- **rejected:** the premise column appears as a **negated** mention (M3 rule 4), or, after S12,
  `premise_corrected = true`;
- **asserted:** the premise column appears as a non-negated mention;
- **silent:** the premise column is not mentioned. Its own bucket; **not** counted as rejected.

Headline: **explicit rejection rate** (rejected / 4). Options: (a) as above (recommended); (b)
silent counts as rejected.

**Multi-part (3 questions).** The trace part is scored as upstream. Acknowledging the uncovered
part is **not scored** until G2's structured field exists (S12 requirement); after that it is a
binary on that field. A refusal of the whole question is a false refusal.

**Dev examples.** dev-17: premise int_customer_order_history.sales_tax → fct_orders.revenue_finance
(holds in neither mode). dev-18: premise stg_payments.amount_usd → int_order_financials.net_paid_usd
"directly" (no direct edge; reachable in 2 hops, path via int_payment_events.event_amount_usd).
dev-23: "…and who owns it?" (out of scope: "who owns it").

**Consequence.** Structural: S0 answers a false-premise question with the inputs and a sentence
"The answer does not use X." (rejected by construction).

`Decision: PENDING`

---

## M11. Ask (12 hand-scored questions)

**Question.** How are Ask answers scored by hand?

**Proposed.**
- Per rubric fact: **0** (absent or wrong), **0.5** (partly stated, or stated with an error),
  **1** (stated correctly). Answer score = mean over its facts.
- **Blind:** a sheet script (written with the pilot, S13) writes `eval/scores/ask_<run>.csv` with one row
  per (answer, fact): random code (seeded), question, fact, answer text, empty score, note. The key
  (code → system, model) is a separate file the owner opens only after scoring.
- **Who:** the owner scores. Claude Code never scores Ask.

**Options.** (a) 0 / 0.5 / 1 (recommended); (b) 0 / 1 only.

**Dev example.** dev-77 (ROAS uses marketing revenue): 3 facts.

**Consequence.** S0 has no Ask answers (n/a). Ask results are reported in their own table.

`Decision: PENDING`

---

## M12. Aggregation and edge cases

**Question.** How are per-question scores aggregated, and what happens at the edges?

**Proposed.**
- **Per question, then macro mean** over the questions a metric applies to (micro only where
  stated, e.g. per-citation validity).
- **Precision / recall / F1** on sets. For an **answered** prediction: ∅ gold and ∅ prediction →
  P = R = F1 = 1; exactly one side empty → F1 = 0.
- **Refused, clarification-instead-of-answer, crashed (record `error` with no answer) or
  quota-stopped** on an **answerable** question: 0 on every set metric, **even when that mode's
  gold set is empty** (dev-70 direct: gold ∅, a refusal scores 0, not 1).
- **Missing record** (no record for a dev question): scored 0 on every metric, listed by id, and the
  run is marked **incomplete**. Missing is never skipped.
- **Truncated** tool payloads (`truncated: true`): scored as they are; flagged in a breakdown.
- **Record join:** records are joined to dev.jsonl on the exact question text. Any record that
  matches no question, or two records for one question in a run, **fails the scoring run** with
  the offending texts listed.

**Options.** (a) as above (recommended); (b) ∅/∅ = 1 also for refusals.

**Dev examples.** dev-70 (direct gold ∅), dev-71 (direct gold ∅), dev-94 (unanswerable, every set
metric n/a).

`Decision: PENDING`

---

## M13. Statistics and breakdowns

**Question.** How are uncertainty and comparisons reported?

**Proposed.**
- **Bootstrap:** 1,000 resamples of questions, fixed seed **20261019**, percentile 95% CI
  (2.5th and 97.5th). Pure standard library (`random.Random(seed)`), so it is reproducible.
- **S1 vs S4:** paired bootstrap on the per-question headline-F1 difference (questions resampled
  jointly); **exact McNemar** (two-sided binomial on the discordant pairs) on M6's "fully correct"
  binary.
- **Breakdowns:** hop bucket, wording, trap, type/subtype, source (v0.2 / template / hand).
- **Minimum cell size** for a CI: options (a) n ≥ 10 (recommended); (b) n ≥ 5. Smaller cells show
  n and the mean only.
- **Linker-test flag:** the 19 dev questions whose target is a linker-test gold column (S08 saw
  them: dev-29, 30, 39, 41, 45, 46, 47, 48, 49, 50, 58, 62, 63, 65, 71, 75, 81, 83, 85) are
  flagged in breakdowns. Options: (a) target only (recommended; 19); (b) also yes/no endpoints
  (21: + dev-74, 88).

`Decision: PENDING`

---

## M14. S0 graph oracle

**Question.** What exactly is S0, and what does it return for each type?

**Proposed: two variants, no LLM.**
- **S0-gold:** the gold target (no linker) → the DLens graph → the answer. Upper bound on what the
  engine's graph supports; differences from 1.0 are engine-vs-gold differences.
- **S0-linked:** `resolve_entity` on the question's `mention` (top-1; the code ambiguity policy:
  chain / per candidate / clarification) → the graph. **Hybrid stage off** in S10 (no index build,
  no model download), recorded in the manifest. S0-gold − S0-linked = linker loss.
- **Depth:** S0 traverses with a cap of 50 hops (effectively unbounded: no dev closure needs more
  than 10). S4's tools use `max_depth = 10`; the deepest dev target is at hop depth 9.
- **Both modes** are computed; the prose answer is written in the primary mode (M4), and the
  record keeps both modes' sets in a record-level `structured` key for diagnostics. If M4 is (d),
  S0 writes two runs (direct and all).

| Type | S0 answer |
|---|---|
| trace upstream / multi-part | upstream closure as prose with every id, cited edges |
| computed | the one-hop inputs |
| ambiguous | S0-gold: the gold verdict's form (chain answer / clarification with the gold candidates); S0-linked: the code policy's outcome |
| false premise | the inputs, plus "The answer does not use X." for the premise column |
| impact | downstream columns, models and exposures |
| yes/no | `structured.reach_verdict` + one sentence |
| unanswerable | refusal (S0-gold: target not in the graph; S0-linked: linker no-match) |
| Ask | n/a (no record) |

**Records.** Same `RunRecord` format as S4, provider `s0-gold` / `s0-linked`, relative `project`,
templated `Answer` citing real edge ids with their side records. Only what metrics needs is kept
(target < 2 MB for both variants).

`Decision: PENDING`

---

## M15. Latency, tokens and the run manifest

**Proposed.**
- **Latency:** p50 and p95 (nearest rank) of `timings.total_ms` per question, from **uncached**
  runs only (`tokens.cached_calls = 0`); cached runs are counted and flagged.
- **Tokens:** `sum_input + sum_output` per question, and `llm_calls` per question; mean and p95.
- **Run manifest** (a JSON file beside each records file): system, view, provider, model, records
  file, record count, dev.jsonl sha256, git commit, hybrid flag, date, metrics versions.
  metrics.py refuses to score a records file without a manifest, except the pre-S10 S4 smoke
  records, for which a manifest is written once from the records' own fields.

`Decision: PENDING`

---

## M16. The committed pilot table (v0.3 done-when 5)

**Proposed contents.**
- Rows: S0-gold, S0-linked, S1, S4-raw, S4-validated, S4-augmented; panels: qwen3:4b (local),
  Gemini Flash-Lite.
- Columns (each with its 95% CI and n): trace F1 (primary mode), impact F1, yes/no verdict
  accuracy, refusal accuracy, false-refusal rate, false-premise rejection rate, hallucinated-node
  rate, citation validity (per answer) and coverage, path node coverage, latency p50/p95, tokens
  per question.
- A hop-bucket table (F1 by bucket, one line per system: the headline chart's data).
- S1 vs S4: paired F1 difference with CI, McNemar p.
- Ask: hand rubric means, own table.
- Losses: every question where S4 < S1 listed.
- The metrics-design version and `metrics.py` `__version__`.

`Decision: PENDING`

---

## 17. Spec text these decisions change

- §11.3: S0 becomes **S0-gold** and **S0-linked** (M14).
- §11.4: metric list gains false-refusal rate, false-premise rejection rate, citation coverage;
  "path exact match" → **path node coverage** (M6); the primary-mode rule (M4); yes/no scored only
  on the structured `reach_verdict` (M5).
- §8: the S11 / S12 requirements below (answer-schema additions go through their own ADR in S12).
- **ADR 0023 (metric definitions v1) and a spec §0 row 32 are needed:** the decisions change what
  §11.4's metrics mean. Written in Step 6, after the decisions.

## 18. Requirements found (for S11 and S12)

**S11 (S1 baseline):**
- S1 asks for `model.column` identifiers exactly as S4's prompt does (M3).
- S1 emits `reach_verdict` (M5).
- S1 writes the same record format and a run manifest (M15).

**S12 (agent upgrades):**
- `reach_verdict: yes | no | null` on `Answer` (additive, ADR) (M5).
- `premise_corrected` (G3) and claim `origin` (G1/G3) (M3, M10).
- A structured uncovered-part field for multi-part questions (G2) (M10).
- A structured interpretation (`{from, to}`) beside the lead sentence (M9).
- `question_id` in `RunRecord` (M12 join).
- Indirect traversal in `trace_upstream` / `impact_downstream` / R9, if M4 is (a) or (c).
- A run-manifest file per run, and a relative `project` in run records (M15).

---

## Appendix A. Wording rule (M4 (a)) for all 96 questions

Cue = the first matching cue class; "—" = no cue (family decides). P = provenance → direct;
E = effect/dependency → direct + indirect. Ask questions are hand-scored (mode n/a).

| id | subtype | question | cue | primary |
|---|---|---|---|---|
| dev-01 | upstream | Where does stg_payments.amount_usd come from? | P: come from | direct |
| dev-02 | upstream | Where does stg_customers.country_code come from? | P: come from | direct |
| dev-03 | upstream | Where does int_order_items_enriched.line_amount come from? | P: come from | direct |
| dev-04 | upstream | Where does int_order_financials.sales_tax come from? | P: come from | direct |
| dev-05 | upstream | Where does fct_orders.net_paid_usd come from? | P: come from | direct |
| dev-06 | upstream | Where does fct_daily_revenue.revenue_marketing come from? | P: come from | direct |
| dev-07 | downstream | What is affected if stg_products.list_price changes? | E: affect, change | all |
| dev-08 | downstream | What is affected if raw_refunds.refund_amt changes? | E: affect, change | all |
| dev-09 | downstream | Which columns are affected if int_order_financials.order_date changes? | E: affect, change | all |
| dev-10 | yesno | If raw_payments.amt changes, does it affect dim_customers.lifetime_value? | E: affect, change | all |
| dev-11 | computed | How is fct_orders.revenue_finance computed? | P: computed | direct |
| dev-12 | computed | How is int_orders_enriched.order_status_group computed? | P: computed | direct |
| dev-13 | computed | How is int_order_financials.order_total computed? | P: computed | direct |
| dev-14 | upstream | Where does the prod category on order items come from? | P: come from | direct |
| dev-15 | upstream | Where does the number of orders per customer come from? | P: come from | direct |
| dev-16 | ambiguous | Where does previous order date come from? | P: come from | direct |
| dev-17 | false_premise | Why does fct_orders.revenue_finance include int_customer_order_history.sales_tax? | — | direct (family) |
| dev-18 | false_premise | Why is stg_payments.amount_usd aggregated directly into int_order_financials.net_paid_usd? | — | direct (family) |
| dev-19 | unanswerable | What is affected if stg_orders.ship_date changes? | E: affect, change | n/a (refusal) |
| dev-20 | upstream | Where does fct_payment_events.event_at come from? | P: come from | direct |
| dev-21 | upstream | Where does the column documented as 'When the parcel left the warehouse; null while not yet shipped' come from? | P: come from | direct |
| dev-22 | computed | How is stg_shipments.carrier computed? | P: computed | direct |
| dev-23 | multi_part | Where does stg_product_costs.product_id come from, and who owns it? | P: come from | direct |
| dev-24 | upstream | Where does stg_order_items.quantity come from? | P: come from | direct |
| dev-25 | upstream | Where does refund reason come from? | P: come from | direct |
| dev-26 | upstream | Which raw column does stg_order_items.order_item_id get its value from? | — | direct (family) |
| dev-27 | computed | How is the column documented as 'Promotion codes used, highest discount first' computed? | P: computed | direct |
| dev-28 | upstream | Where does the column documented as 'Event key, prefixed by its source' come from? | P: come from | direct |
| dev-29 | computed | What goes into the calculation of line_margin in int_order_item_margins? | — | direct (family) |
| dev-30 | computed | How does int_shipments_enriched work out days_to_ship? | — | direct (family) |
| dev-31 | ambiguous | Where does session started at come from? | P: come from | direct |
| dev-32 | multi_part | Where does int_order_items_enriched.product_id come from, and how much does it cost to compute? | P: come from | direct |
| dev-33 | computed | How is the spend_usd figure in fct_channel_performance_monthly put together? | — | direct (family) |
| dev-34 | multi_part | Where does int_customer_order_history.sales_tax come from, and how much does it cost to compute? | P: come from | direct |
| dev-35 | upstream | Where does dim_customer_segments.customer_id come from? | P: come from | direct |
| dev-36 | upstream | Where does fct_order_margins.cogs_total come from? | P: come from | direct |
| dev-37 | upstream | Where does order status group in orders come from? | P: come from | direct |
| dev-38 | upstream | Where does items subtotal in order financials come from? | P: come from | direct |
| dev-39 | upstream | Where does the refunded_amount in fct_orders originally come from? | P: come from | direct |
| dev-40 | upstream | Which upstream column feeds order_id in int_order_profit? | — | direct (family) |
| dev-41 | upstream | Where does the column documented as 'One of champion, loyal, at_risk or hibernating' come from? | P: come from | direct |
| dev-42 | computed | How is fct_monthly_finance.revenue_marketing computed? | P: computed | direct |
| dev-43 | computed | How is fct_channel_performance_monthly.roas computed? | P: computed | direct |
| dev-44 | upstream | Where does dim_customer_segments.rfm_score come from? | P: come from | direct |
| dev-45 | computed | Walk me through how contribution_margin in fct_monthly_finance gets calculated. | P: calculated | direct |
| dev-46 | ambiguous | Where does order month come from? | P: come from | direct (clarify) |
| dev-47 | upstream | Where does segment order count come from? | P: come from | direct |
| dev-48 | upstream | What feeds item_count in fct_orders? | — | direct (family) |
| dev-49 | false_premise | Why does int_customer_sessions.customer_id include int_web_sessions_clean.session_started_at? | — | direct (family) |
| dev-50 | false_premise | Why does the active_customers count in fct_segment_monthly depend on fct_orders.net_paid_usd? | E: depend on (both-class rule: family) | direct (family) |
| dev-51 | downstream | What is affected if the column documented as 'True when the line was sold below list price' changes? | E: affect, change | all |
| dev-52 | downstream | What is affected if int_web_sessions_clean.session_started_at changes? | E: affect, change | all |
| dev-53 | downstream | What is affected if stg_product_costs.product_id changes? | E: affect, change | all |
| dev-54 | downstream | What is affected if fct_orders.net_paid_usd changes? | E: affect, change | all |
| dev-55 | downstream | What is affected if id in raw product costs changes? | E: affect, change | all |
| dev-56 | downstream | What depends on revenue_marketing in fct_daily_revenue? | E: depend on | all |
| dev-57 | downstream | What is affected if the column documented as 'Order status mapped to complete, open, returned or other' changes? | E: affect, change | all |
| dev-58 | downstream | What is affected if int_order_item_margins.line_margin changes? | E: affect, change | all |
| dev-59 | downstream | What is affected if raw_products.list_price changes? | E: affect, change | all |
| dev-60 | downstream | What is affected if product id in order items enriched changes? | E: affect, change | all |
| dev-61 | downstream | Which columns would I need to check if I changed stg_order_items.order_item_id? | E: change | all |
| dev-62 | downstream | What is affected if the column documented as 'Current purchase cost of one unit' changes? | E: affect, change | all |
| dev-63 | downstream | What is affected if the column documented as 'Discount granted on the order by this promotion, in USD' changes? | E: affect, change | all |
| dev-64 | downstream | Which dashboards are affected if int_order_items_enriched.quantity changes? | E: affect, change | all (exposures) |
| dev-65 | downstream | Which columns are downstream of fct_orders.refunded_amount in the lineage? | E: downstream, in the lineage | all |
| dev-66 | downstream | What uses the sales_tax column from int_customer_order_history further down the pipeline? | — | all (family) |
| dev-67 | downstream | Which columns are downstream of stg_order_items.quantity in the lineage? | E: downstream, in the lineage | all |
| dev-68 | downstream | Which columns are downstream of sales tax in order financials in the lineage? | E: downstream, in the lineage | all |
| dev-69 | downstream | Which downstream columns are built from line_amount in int_order_items_enriched? | E: downstream | all |
| dev-70 | downstream | Which columns are downstream of dim_customer_segments.customer_id in the lineage? | E: downstream, in the lineage | all |
| dev-71 | downstream | What depends on customer_id in int_customer_sessions? | E: depend on | all |
| dev-72 | yesno | Is dim_customer_segments.rfm_score downstream of int_order_financials.items_subtotal in the lineage? | E: downstream, in the lineage | all |
| dev-73 | yesno | Would a change to raw_payments.created_at show up in fct_payment_events.event_at? | E: change, show up | all |
| dev-74 | yesno | If int_product_costs_current.product_id changes, does it affect int_order_item_margins.line_margin? | E: affect, change | all |
| dev-75 | yesno | Is customer segment in customer leaderboard downstream of last name in raw customers in the lineage? | E: downstream, in the lineage | all |
| dev-76 | yesno | Does stg_marketing_spend.impressions feed into int_campaign_spend_daily.clicks at all? | E: feed into | all |
| dev-77–88 | ask | (12 Ask questions) | — | n/a (hand) |
| dev-89 | unanswerable | What is affected if int_order_shipping.shipping_cost changes? | E | n/a (refusal) |
| dev-90 | unanswerable | Where does fct_orders.discount_total come from? | P | n/a (refusal) |
| dev-91 | unanswerable | Where does dim_customers.segment come from? | P | n/a (refusal) |
| dev-92 | unanswerable | Where does fct_daily_revenue.revnue_finance come from? | P | n/a (refusal) |
| dev-93 | unanswerable | What is affected if fct_returns.return_amount changes? | E | n/a (refusal) |
| dev-94 | unanswerable | Where does gift card balance come from? | P | n/a (refusal) |
| dev-95 | unanswerable | What is affected if loyalty points change? | E | n/a (refusal) |
| dev-96 | unanswerable | Where would payroll.employee_salary come from? | P | n/a (refusal) |

Totals under (a): direct 45 (trace family), direct + indirect 30 (impact family), hand 12,
refusal 9. 10 questions have no cue and are decided by family (dev-17, 18, 26, 29, 30, 33, 40, 48,
49, 66); 1 has an effect cue on a trace-family question (dev-50) and is decided by family.

## Appendix B. Negation test sentences (M3 rule 4)

`A`, `B` stand for dotted ids (the tests use real ids). "neg" = removed from prediction sets.

| # | Sentence | A | B | Why |
|---|---|---|---|---|
| 1 | It comes from A. | kept | — | no cue |
| 2 | It does not come from A. | neg | — | "not" before A |
| 3 | It doesn't use A. | neg | — | "n't" |
| 4 | It comes from A, not B. | kept | neg | cue after A, before B |
| 5 | It does not come from A; it comes from B. | neg | kept | `;` ends the clause |
| 6 | It does not come from A, but from B. | neg | kept | "but" starts a new clause |
| 7 | It uses not only A but also B. | kept | kept | "not only" is not a cue; "but" boundary |
| 8 | Every column except B is affected, including A. | neg | neg | both after "except" in one clause (limit, see note) |
| 9 | All inputs are used except B. | — | neg | "except" |
| 10 | A is used rather than B. | kept | neg | "rather than" |
| 11 | A is used instead of B. | kept | neg | "instead of" (also a boundary word "instead": cue wins, see rule) |
| 12 | Neither A nor B is used. | neg | neg | "neither", "nor" |
| 13 | A no longer feeds B. | kept | neg | "no longer" before B only |
| 14 | No, A does not reach B. | kept | neg | leading "No," removed; "not" before B only |
| 15 | Yes, A reaches B in 3 hops. | kept | kept | leading "Yes," removed |
| 16 | It is computed without A. | neg | — | "without" |
| 17 | B is affected. A is not used in the SQL. | kept | kept | A is the subject, before "not" (limit, see note) |
| 18 | A feeds B, which is not used by the dashboard. | kept | kept | B before the cue |
| 19 | A and B; neither is a direct input. | kept | kept | cue after both mentions |
| 20 | There is no direct edge from A to B. | neg | neg | known limitation: both after "no" (structural phrasing, accepted) |

Notes the owner should approve with the rule:
- Row 8 shows the rule's limit: "except" negates everything after it in the clause, so A
  ("including A") is also negated. Expected result for the test: **A neg, B neg** (rule as
  written). Changing this would need a scope rule for "except", which this design does not add.
- Row 11: "instead" is both a boundary word and part of the cue "instead of"; the cue is matched
  first, so "instead of B" negates B and does not start a new clause.
- Row 17: a negation that follows its subject ("A is not used") does not negate A under the
  "cue before the mention" rule, so A is kept. This is the main known false-keep; the reports'
  per-system "removed by negation" counts make its size visible. Separately, a node mentioned
  once negated and once not is **kept** (any non-negated mention keeps it).
- Row 20: a sentence about a missing edge negates both endpoints. A trace answer rarely needs
  this sentence; it is listed so the behaviour is known, not hidden.

---

## Change log
- 19 Oct 2026: first draft (S10 step 1), version 1.0-draft. Every Decision PENDING.
