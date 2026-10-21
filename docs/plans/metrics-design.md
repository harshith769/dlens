# Metrics design (S10, v0.3 D3)

**Metrics-design version:** 1.2 (S12b, 20 Oct 2026: the B2 + B5 policy of
`docs/plans/s12-design.md`; changes M9, M10 and adds Appendix D). Last approved version: 1.1
(owner amendments to M7 and M9, 19 Oct 2026; 1.0: every Decision set by the owner, 19 Oct 2026).
Every scored report names this version and `eval/metrics.py`'s `__version__`.
**Status:** v1.2 **Accepted**, owner, 20 Oct 2026 (STOP 1 of S12b, with one change to the M9
mention branch); implemented by `eval/metrics.py` 1.3.0 (0207837, 21 Oct 2026), every Appendix D
row passing against the extractor. **Every definition is the owner's decision**, recorded on each `Decision:` line.
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

**Options for inputs-scored questions** (computed 11, false premise 4):
- (s) **Strict inputs F1**: precision and recall both against the gold one-hop inputs.
- (t) **Closure-tolerant inputs F1**: recall over the gold inputs; precision counts a predicted
  mention as wrong only if it is **outside the target's upstream closure** in the primary mode
  (computed by `dlens.gold_spec.upstream` from `lineage_spec.yml`, since computed and
  false-premise gold carry no `upstream` field).
- Whichever is chosen is the headline; the other is reported as a diagnostic.
- Trade-off: (t) does not punish correct context ("quantity comes from raw_order_items.quantity"
  in a "how is line_amount computed?" answer), but an answer that lists the whole closure scores
  well on it. (s) rewards exactly the one-hop answer the question asks for, and punishes true but
  extra context.
- Upstream and impact questions keep **strict** precision either way: their gold is already the
  full closure, so nothing true lies outside it.

**Recommendation.** Trace upstream: (a) closure F1 as the headline, with sources-F1 and inputs-F1
as diagnostics. "Where does X come from?" asks for the whole chain; sources alone would reward
skipping every hop, and inputs alone would reward stopping after one. Impact: (a) separately; a
combined set lets 60 columns drown 2 dashboards. Inputs-scored questions: (s) strict as the
headline, (t) as a diagnostic: "How is X computed?" asks for the formula's inputs, and (t) cannot
tell a precise answer from a closure dump.

| Type / subtype | n | Gold field | Headline metric | Diagnostics |
|---|---|---|---|---|
| trace / upstream | 24 | `upstream[mode]` | node-set F1 | sources F1, inputs F1, path node coverage (M6) |
| trace / computed | 11 | `inputs.direct` (+ indirect `from`s in all mode) | inputs F1, strict (s) or closure-tolerant (t) | the other of (s) / (t) |
| trace / ambiguous | 3 | `verdict`, `candidates`, `upstream` | verdict correct (M9); chain: upstream F1 of the gold target | candidate recall |
| trace / multi-part | 3 | `upstream`, `out_of_scope` | upstream F1 (as upstream) | uncovered part named (M10; v1.2 draft: field or prose, own row) |
| trace / false premise | 4 | `inputs`, `premise` | inputs F1 ((s) or (t)) + premise rejection (M10) | silent / asserted counts |
| impact / downstream | 24 | `downstream[mode]`, `models[mode]`, `exposures[mode]` | columns F1 (dev-64, `focus: exposures`: exposures F1) | models F1, exposures F1 |
| impact / yes-no | 6 | `reach[mode]` | verdict accuracy (M5) | heuristic prose verdict (labelled) |
| ask / meaning | 12 | `facts` | hand rubric (M11) | — |
| unanswerable | 9 | `verdict: refused` | refusal correct (M9) | `closest` named (not scored) |
| interpreted near-miss | 0 in dev | `interpretation` | M9 rule (v1.2 draft: field or prose), then scored as its underlying type | — |

**Dev examples.** dev-03 (upstream 4 direct; sources 2; inputs 2). dev-09 (24 / 13 / 1 direct).
dev-64 ("Which dashboards are affected…", exposures headline).

**Consequence.** S0 is exact on every field it can compute (M14). S1 and S4 are scored on the same
fields through the same extractor (M3). Ask is outside every automatic number.

`Decision (owner, 19 Oct 2026):` trace upstream (a) closure F1; impact (a) columns, models, exposures scored separately; inputs-scored questions (s) strict inputs F1 as the headline, (t) closure-tolerant as a diagnostic.

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

`Decision (owner, 19 Oct 2026):` (a) short ids, separate model and exposure sets, target excluded.

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
1. **Dotted ids (identifier filter).**
   - *Paths first:* any token containing `/`, or ending in a file extension (`.sql`, `.yml`,
     `.yaml`, `.csv`, `.py`, `.md`, `.json`, `.txt`), is removed whole before matching, including
     any bare model name inside it (`models/marts/fct_orders.sql` yields no mention at all).
   - *Candidates:* tokens of the form `name.name` (also the 3–4 part fully-qualified form, cut per
     M2), letters/digits/underscore, first character a letter or underscore.
   - *Stop list:* `e.g`, `i.e`, `etc`, `vs`, `cf`, `al` (as in "et al.") never match.
   - A candidate is a **mention** only if (a) it is in the gold inventory (M8), or (b) its model
     part is a known model or seed name, or (c) its model part looks dbt-style: contains `_`, or
     starts with `stg_`, `int_`, `fct_`, `dim_`, `raw_`, `mart_` or `base_`.
   - A mention in the inventory counts toward the node sets; a mention outside it is a
     hallucination candidate (M8). Anything else (`github.com`, `v0.3`, `3.5`) is plain text.
   - The test rows for this filter are Appendix C.
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
     "whereas", "while", "instead", "including", "plus" (a comma before them is part of the
     boundary). A relative clause opened by ", which", ", that" or ", who" and closed by the next
     comma (or the sentence end) is its own clause, so a cue inside it does not reach the main
     clause (Appendix B row 23). A leading answer particle "Yes," / "No," is removed before the
     analysis.
   - *Pre-mention cue*: inside the clause and **before** the mention: "not", "n't", "no",
     "never", "without", "rather than", "instead of", "except", "excluding", "other than",
     "neither", "nor", "no longer". The two-word phrase "not only" is **not** a cue.
   - *Post-mention cue*: the mention is **immediately** followed (optionally after the word
     "itself" or "column") by "is not", "isn't", "are not", "aren't", "was not", "wasn't",
     "does not", "doesn't", "did not", "didn't", "is never", "never", "no longer" or "has no".
     Adjacency is required: a comma or a relative word ("which", "that", "who") between the
     mention and the cue breaks it.
   - *Value-word exemption:* a cue (pre or post) that is followed in its clause by a value word
     ("null", "nullable", "empty", "zero", "negative", "unique", "missing", "blank") **before the
     next mention or the clause end** is not a negation: it describes values, not lineage ("where
     A is not null", "A is never null" → A kept). Appendix B rows 28–31.
   - A mention is negated if either cue applies. Every cue word is matched as a whole word,
     case-insensitive.
   - A node mentioned once negated and once not is **kept** (any non-negated mention keeps it).
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

`Decision (owner, 19 Oct 2026):` rules 1–5 as revised, including the identifier filter (Appendix C), the relative-clause rule and the value-word exemption narrowed to "before the next mention" (Appendix B rows 28–31); bare names (i) never counted.

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

`Decision (owner, 19 Oct 2026):` (a) wording rule; Appendix A approved (45 direct, 30 direct + indirect).

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

`Decision (owner, 19 Oct 2026):` (a) structured `reach_verdict` only; prose heuristic a labelled diagnostic.

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

`Decision (owner, 19 Oct 2026):` (a) path node coverage; ordered exact match an S0/S4 diagnostic; McNemar on (a) "question fully correct".

---

## M7. Citation validity

**Question.** When is a citation valid, and how is validity reported?

**Check (independent, on disk; metrics.py never imports the validator).** For each citation in an
answer's `citations`:
1. the file exists under the corpus project directory (the path is resolved and must stay inside
   it);
2. `1 ≤ line_start ≤ line_end ≤` the file's line count;
3. the cited lines contain the **required column**, matched as a whole word, case-insensitive:
   - edge citation (`e_`), options: (i) the edge's `to` column; (ii) its `from` column;
     (iii) either; (iv) **by edge kind**: a direct edge → its `to` column (the line that writes
     the output column); an indirect edge (JOIN, FILTER, GROUP_BY, WINDOW, SORT, CONDITIONAL)
     → its `from` column (a clause-level citation names the key, not the output).
     **Recommended: (iv).**
     *Evidence (DLens graph of synthetic_shop, read-only, 19 Oct 2026; a fact about where
     citations point, not a system result).* All 621 indirect edges have line-level citations.
     Their cited lines name the `from` column in 598 (70 of them also name `to`), only the `to`
     column in 2, and neither in 21. Under (i), 549 of 621 indirect citations would be invalid.
     Three examples:
     - GROUP_BY `fct_orders.customer_id → dim_customers.first_order_date`,
       `models/marts/dim_customers.sql:9` `group by customer_id`: names `from`, not `to`.
     - FILTER `int_inventory_daily.product_id → fct_inventory_status.as_of_date`,
       `models/marts/fct_inventory_status.sql:9-12` `qualify row_number() over (partition by
       product_id, …) = 1`: names `from`, not `to`.
     - SORT `dim_customers.lifetime_value → fct_customer_leaderboard.customer_id`,
       `models/marts/fct_customer_leaderboard.sql:9` `order by customers.lifetime_value desc,
       customers.customer_id`: names `from` (and `to`, only because the sort list holds it).
     The 23 indirect citations without the `from` name are JOINs whose clause names a CTE column
     (`margins_monthly.margin_month` ×8, `adjustments_monthly.adjustment_month` ×8,
     `revenue_monthly.finance_month` ×7). Under (iv) these fail.
     **Sub-option (iv-k)**, for indirect edges whose `from` column is not on the cited lines:
     accept the clause key as written only if metrics itself confirms (1) the key's model part
     is a CTE defined in the cited file (a case-insensitive `<name> as (` match) and (2) the key
     appears in the cited lines. The record's key alone is never enough.
     *Finding (19 Oct 2026):* the three names above are **derived-table aliases**, not CTEs
     (`fct_monthly_finance.sql`: `( select … ) as revenue_monthly`). Guard (1) as written
     therefore accepts **none** of the 23. Option (iv-k+): guard (1) also accepts a
     derived-table alias, matched as `) as <name>` **and** used as a qualifier (`<name>.`) in
     the same file. On the corpus this matches exactly `adjustments_monthly`, `margins_monthly`
     and `revenue_monthly`. The qualifier test is what excludes column aliases
     (`sum(x) as gross_margin`). S4's tools return no indirect edges today, so this matters once
     indirect traversal lands (S12).
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
  valid if every citation is valid. An answered answer with **zero citations is invalid**,
  except (v1.1) an answer whose own structured `reach_verdict` is "no" and that has zero file
  citations: n/a, since a correct "No" has nothing to cite. Its citations, if any, are checked as
  usual. The system's verdict decides, never the gold.
- **Citation coverage:** share of claims with ≥ 1 citation.
- **Disagreement with R3:** the count of citations where this re-check and the validator's R3
  outcome (read from the record's `validation` failures, no import) disagree, listed. Only ids
  the R3 check actually ran on count (v1.1: ledger ids of a record whose validation ran).

**Options for the per-answer rule.** (a) as above (recommended); (b) answers with zero citations
excluded instead of invalid.

**Dev example.** dev-01's gold edge raw_payments.amt → stg_payments.amount_usd: a citation of
`models/staging/stg_payments.sql` must contain `amount_usd` on its lines under (i) and (iv).

**Consequence.** S4-validated passed R3 by construction, so disagreements there are expected to be
few and each one is listed. S1 has no validator; the same check applies.

`Decision (owner, 19 Oct 2026):` (iv) by edge kind with (iv-k+); per-answer rule (a). Guard, checked by metrics itself: the clause key's model part is either a CTE (`<name> as (`) or a derived-table alias (`) as <name>` **and** used as `<name>.` elsewhere in the same file), **and** the key appears on the cited lines. Required test: a cast alias such as `cast(x as int) as amount`, with no `amount.` qualifier anywhere in the file, does **not** pass the guard. **Amended (owner, 19 Oct 2026, v1.1):** an answer whose structured `reach_verdict` is "no" and that has zero file citations is n/a for per-answer citation validity; with citations it is checked as usual; the system's own verdict decides, never the gold.

---

## M8. Hallucinated-node rate

**Question.** What counts as a hallucinated node?

**Definition (proposed).**
- **Inventory:** the gold spec, not the graph: the 391 columns of `lineage_spec.yml` (318 model +
  73 seed), its 49 model and 14 seed names, and the exposures in `traps.yml` (`finance_dashboard`,
  `marketing_dashboard`).
- **Numerator:** distinct mentions (negated or not) that passed the M3 rule 1 identifier filter
  and are not in the inventory, excluding every id the question text itself writes (an
  unanswerable question's non-existent id echoed in a refusal is not a hallucination). Tokens the
  filter drops (`e.g`, `github.com`, `v0.3`, file paths) are never hallucinations.
- **Denominator:** distinct mentions (filtered the same way) in the answer.
- **CTE references:** metrics builds a CTE-name list with a plain regex (`<name> as (`,
  case-insensitive) over the corpus model SQL files, never from the engine. A dotted token whose
  model part is on that list is neither a node nor a hallucination; it is counted in its own
  "CTE reference" diagnostic. On synthetic_shop the list has 9 names (`attributed_daily`,
  `cash_per_order`, `item_agg`, `item_margins`, `latest_snapshots`, `order_agg`,
  `refunds_per_order`, `rfm_base`, `rfm_scores`), none equal to a model or seed name. Option
  (a+): the list also takes derived-table aliases under the M7 (iv-k+) test (+3:
  `adjustments_monthly`, `margins_monthly`, `revenue_monthly`). Without (a+), a quoted
  `margins_monthly.margin_month` is a hallucination candidate.
- **Aggregation:** per answer, then macro mean over answers with ≥ 1 dotted mention; also the share
  of answered answers with ≥ 1 hallucinated node.
- **Known limit:** a hallucinated id with a plain-word model part (`orders.total`) fails the M3
  identifier filter and is not counted. This can only **undercount** hallucinations.

**Options.** (a) as above, with the CTE list (recommended); (a+) as (a), with derived-table
aliases added to the list; (b) negated mentions excluded from both counts.

**Dev examples.** dev-92 "Where does fct_daily_revenue.revnue_finance come from?" — a refusal
naming `fct_daily_revenue.revnue_finance` is not a hallucination; one naming
`fct_daily_revenue.revenue_net` is.

**Consequence.** Structural: S4's R4 rule already rejects some of these in validated answers; S4-raw
and S1 have no such filter.

`Decision (owner, 19 Oct 2026):` (a+): CTE names and derived-table aliases (same test as M7 (iv-k+)) form the "CTE reference" list; neither nodes nor hallucinations.

---

## M9. Refusal, ambiguity and interpretation verdicts

**Question.** How are refusals, clarifications, chains and interpretations scored?

**Proposed rules.**
- **Refusal accuracy:** on the 9 unanswerable questions, the share refused. A clarification on an
  unanswerable question is not a refusal (wrong).
- **False-refusal rate:** on answerable questions (gold verdict answered, chain, partial or
  clarify), the share refused. dev-17's legacy `or_refused` is **not** honoured in the headline.
- **Chain** (dev-16, dev-31): the headline reads **prose only**, so S1 and S4 are judged the same
  way: correct if the answer is answered (not refused, no clarification) and the gold `target`
  (the most downstream candidate) is a non-negated mention. Then scored as upstream. The record's
  ambiguity mode (`chain`, downstream = target) is an **S4-only diagnostic**.
- **Clarify** (dev-46): reads the shared schema field `clarification`: correct if it is set and
  its candidates ⊇ gold `candidates`, **or** (v1.1) the answer is answered and every gold
  candidate is a non-negated mention (a per-candidate answer). Answering only one candidate is
  wrong.
- **Refusal** reads the shared schema field `refused`, never prose.
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

`Decision (owner, 19 Oct 2026):` rules as drafted; `closest` not scored (diagnostic only); `or_refused` not honoured. **Amended (owner, 19 Oct 2026, v1.1):** a clarify-gold question is correct with a clarification listing every gold candidate **or** an answered answer naming every gold candidate as a non-negated mention; dev.jsonl gold and spec §8 unchanged.

### M9 v1.2: interpreted near-miss, field or prose (s12-design B2 + B5, ADR 0028)

Replaces the "Interpreted near-miss" bullet above when decided. 0 dev questions carry
`gold.interpretation`; test questions may (questions-design D5b).

- **Rule.** Let G = `short_id(gold.interpretation.column)`. Correct iff the prediction is
  **answered** (kind `answered`: not refused, not a clarification, not crashed or missing) **and**
  at least one branch holds:
  - **field:** the answer's structured `interpretation.to`, normalised by M2, equals G;
  - **prose (lead):** `answer_text` contains a lead "Interpreted A as B." (the M3 rule 3 pattern,
    as `interpretations()` reads it today) with `short_id(B)` = G;
  - **prose (mention):** G is an **identity-kept** column mention of the answer text
    (`answer_text` plus every claim text, in the view being scored): at least one mention of G
    that no **pre-mention cue** negates.
- **Negation in the mention branch (owner change at STOP 1).** Only M3 rule 4's **pre-mention**
  part applies: the clause rules (sentence ends `.` `!` `?` `;`; the boundary words "but",
  "however", "whereas", "while", "instead", "including", "plus"; the ", which / that / who … ,"
  relative clause as its own clause), the pre-mention cue list (with "not only" excluded and the
  pairs "rather than", "instead of", "other than"), the leading "Yes," / "No," removal, and "a
  node mentioned once negated and once not is kept". The **post-mention rule** ("A is not…",
  "A does not…") and therefore the **value-word exemption** do **not** apply in this branch: a
  post-mention cue negates a statement *about* the column, while M9 asks *which* column the
  answer understood ("No, G does not reach H" names G correctly). Known limit: a predicate
  negation keeps the identity ("G is not used" → kept; Appendix D row I5).
  Scope: this branch only. M3's node sets, the M9 v1.1 clarification rule and M10's premise rule
  keep the full M3 rule 4.
  M3 rule 3: in a lead "Interpreted A as B.", B is a mention and A is not.
- **Target exclusion does not apply here.** G is usually the question's target, which M2 removes
  from the node sets; the M9 rule reads the kept-column set *before* that exclusion, as the chain
  rule (above) does.
- **Pass route** (reported, see M10 v1.2 "Pass-route reporting"): `field` (field only), `prose`
  (lead or mention, not field), `both`, `neither` (no branch holds, or not answered).
- **Set metrics gate (unchanged structure).** As in v1.1, an interpreted question that fails
  this rule scores 0 on its set metrics (`score_question`'s `interp_ok`); v1.2 changes only which
  answers pass the gate. On dev this moves no number (0 such questions).
- **Views (ADR 0028).** `interpretation` is set by code before the answer phase from the
  linker's reading (`entity.dotted_column`); it is not a correction of the model's draft. It
  therefore counts in **raw, validated and augmented** alike, read from `final_answer` (the
  draft has no such field). `interpretation_source` is recorded (`code` for every S12 value);
  metrics does not filter on it in v1.2. The prose branches read the view's own answer text
  (raw: the draft, which never holds the code-written lead; the field branch carries the code
  reading into raw). *(Owner, plan approval 20 Oct 2026: all views.)*
- **Systems.** S4: all three branches. S1 (frozen; no field): prose branches only. S0-gold (no
  linker, never interprets) and S0-linked (writes the lead in prose): prose branches only. One
  rule for every system (rule 12).

`Decision (owner, 20 Oct 2026, v1.2):` approved with one change: the mention branch applies only
pre-mention negation (no post-mention rule, no value-word exemption), as written above.

---

## M10. False premise and multi-part

**Question.** How are false-premise and multi-part questions scored while `premise_corrected`
and the G2 field do not exist yet?

**False premise (4 questions).** The inputs set is scored as computed (M1). How the premise is
bucketed depends on where the premise column sits:

- **Case O: the premise column is outside the target's upstream closure** in the primary mode.
  A non-negated mention of it is a false claim, so three buckets:
  - **rejected:** the premise column appears as a **negated** mention (M3 rule 4), or, after S12,
    `premise_corrected = true`;
  - **asserted:** it appears as a non-negated mention;
  - **silent:** it is not mentioned. Its own bucket; **not** counted as rejected.
- **Case U: the premise column is upstream of the target** in the primary mode (a gold path
  exists; the premise is wrong only in how it says they connect, e.g. "directly"). A
  non-negated mention can be true context ("amount_usd reaches net_paid_usd through
  event_amount_usd"), so only two buckets:
  - **rejected:** negated mention, or `premise_corrected = true` after S12;
  - **not rejected:** everything else.

| id | premise | upstream in primary mode (direct)? | case |
|---|---|---|---|
| dev-17 | int_customer_order_history.sales_tax → fct_orders.revenue_finance | no (no in all mode either) | O |
| dev-18 | stg_payments.amount_usd → int_order_financials.net_paid_usd ("directly") | **yes**, 2 hops via int_payment_events.event_amount_usd (also in all mode) | U |
| dev-49 | int_web_sessions_clean.session_started_at → int_customer_sessions.customer_id | no (no in all mode either) | O |
| dev-50 | fct_orders.net_paid_usd → fct_segment_monthly.active_customers | no (no in all mode either) | O |

Headline: **explicit rejection rate** (rejected / 4, both cases). Options: (a) as above
(recommended); (b) silent counts as rejected (case O only).

**Multi-part (3 questions).** The trace part is scored as upstream. Acknowledging the uncovered
part is **not scored** until G2's structured field exists (S12 requirement); after that it is a
binary on that field. A refusal of the whole question is a false refusal.

**Dev examples.** dev-17: premise int_customer_order_history.sales_tax → fct_orders.revenue_finance
(holds in neither mode). dev-18: premise stg_payments.amount_usd → int_order_financials.net_paid_usd
"directly" (no direct edge; reachable in 2 hops, path via int_payment_events.event_amount_usd).
dev-23: "…and who owns it?" (out of scope: "who owns it").

**Consequence.** Structural: S0 answers a false-premise question with the inputs and a sentence
"The answer does not use X." (rejected by construction).

`Decision (owner, 19 Oct 2026):` (a) cases O / U, headline = explicit rejection rate over 4; multi-part uncovered part unscored until G2.

### M10 v1.2: uncovered part and premise correction, field or prose (s12-design B2 + B5, ADRs 0025, 0027)

**The v1.1 false-premise rule, restated exactly (as `eval/metrics.py` 1.2.0 implements it).**
Let P = `short_id(gold.premise.edge.from)`, the mode = M4's primary mode, and **case U** iff
`dlens.gold_spec.reaches(P, gold.premise.edge.to)` in that mode (else **case O**).
`mentioned` = P is a column mention (negated or not); `negated` = every mention of P is negated
(M3 rule 4). `rejected` = `premise_corrected is true` **or** (answered **and** `negated`).
Case U: bucket `rejected` if rejected, else `not_rejected`. Case O: `rejected` if rejected, else
`asserted` if answered and mentioned, else `silent`. Headline `premise_rejected` = bucket is
`rejected`. In v1.1 the `premise_corrected` term is read from the answer without further
condition (raw view: the draft); no S1, S0 or committed S4 record sets it.

**Premise correction under the field-or-prose policy (v1.2 draft).** `premise_corrected` enters
scoring (it is already named in v1.1's rule), with the same strictness as the prose branch:
- **field branch:** `premise_corrected is true` **and** answered **and** no non-negated
  assertion of the premise: in **case O**, P is not a kept mention (a kept mention of P is the
  `asserted` bucket); in **case U** no condition on mentions (a kept mention of P is true context
  there, which is why case U has no `asserted` bucket);
- **prose branch:** answered **and** `negated` (unchanged);
- `rejected` = field branch **or** prose branch. Buckets as above. Pass route: `field` / `prose`
  / `both` / `neither`.
- Change from v1.1: a `premise_corrected = true` answer that is not answered (refused,
  clarification) or that asserts P in case O is no longer `rejected`. No committed record is
  affected (none sets the field).
- `premise_corrected` is LLM-only (ADR 0025); raw reads the draft, validated / augmented the
  final answer. S1 and S0 have no field: prose branch only (S0's "It does not use P." is
  rejected by construction, as v1.1 states).

**Multi-part: uncovered part (3 dev questions; replaces "not scored until G2").** Scored on every
multi-part question as `uncovered_part_correct` (binary, macro mean). The trace part keeps its
upstream F1 (M1); a refusal of the whole question is a false refusal (M9), unchanged.

- **Rule.** Correct iff the prediction is **answered** (kind `answered`) **and** at least one
  branch holds:
  - **field:** some string in the answer's `uncovered_parts` contains a **content word**
    (definitions below). No cue is needed: the field is the cue. A non-empty list with no
    content word (e.g. `["n/a"]`) does not satisfy it.
  - **prose:** some **sentence** of the answer text contains both a content word and a
    **coverage cue**.
- **Content words (from the gold).** Lowercase the gold `out_of_scope` text, split it into word
  tokens (`[a-z']+`), drop the tokens on the stop list. The stop list, exactly:
  `a, an, the, it, its, this, that, these, those, is, are, was, were, be, been, being, do, does,
  did, done, to, of, for, in, on, at, by, with, from, and, or, as, i, you, we, they, them, their,
  who, whom, whose, what, which, when, where, why, how, much, many, can, could, would, should,
  will, there, here, come, comes, came, compute, computes, computed, computing, derive, derives,
  derived, depend, depends, use, uses, used, feed, feeds, column, columns, model, models, table,
  tables, lineage, source, sources, upstream, downstream`.
  On dev: "who owns it" → {`owns`}; "how much does it cost to compute" → {`cost`}.
- **Word match (suffix rule).** For a content word w: base = w without its final "s" when w is
  longer than 3 letters and ends in "s" but not "ss", else w. An answer word t matches w iff
  t = base + x for x in exactly `"", s, es, d, ed, er, ers, ership, ing`. So `owns` matches own,
  owns, owned, owner, owners, ownership, owning; `cost` matches cost, costs, costed, coster,
  costers, costing. Synonyms ("expense", "price", "steward") never match (a stated limit; it can
  only under-credit).
- **Identifier exclusion.** Before words are read from an answer sentence or a field string,
  remove every token that M3 rule 1 removes or considers: paths (rule 1 "paths first"), every
  dotted candidate (`name.name`, 2–4 parts, whether or not it is a mention), and every remaining
  token that contains `_` (snake_case identifiers such as `unit_cost`, `owner_id`). Words inside
  identifiers therefore never match (`stg_product_costs.unit_cost` gives no `cost`). The gold
  side is plain words on dev and needs no exclusion.
- **Coverage cues (prose branch only), exactly**, whole words, case-insensitive: `not`, `no`,
  `never`, `without`, `neither`, `nor`, `cannot`, `unable`, `outside`, `beyond`, `unknown`,
  `unavailable`, any word containing `n't`, and the phrase `out of scope`. The two-word phrase
  "not only" is not a cue (as in M3). The M3 lineage cues "except", "excluding", "rather than",
  "instead of", "other than" are **not** coverage cues.
- **Sentence scope.** Sentences are split exactly as M3's extractor splits them (`.` `!` `?` `;`
  followed by a space or the end), over `answer_text` and each claim's text separately (a claim
  is never joined to the answer text). A leading "Yes," / "No," is removed first (M3). The cue and
  the content word must be in the same sentence, in either order; clause boundaries inside the
  sentence do not matter. A code-written lead "Interpreted A as B." is its own sentence.
- **Pass route:** `field` / `prose` / `both` / `neither` (`neither` also when not answered).
- **Not in any composite.** `uncovered_part_correct` enters no F1 composite (M16), not
  `fully_correct` and not McNemar; it is its own row.
- **Systems.** S4: both branches (raw: the draft's `uncovered_parts` and prose; validated /
  augmented: the final answer's). S1 (frozen; no field) and S0-gold / S0-linked (no field; S0's
  multi-part answer is the trace closure only): prose branch only. One rule for every system.
- **Known limits (listed, not hidden):** a sentence that names the out-of-scope word as data
  with an unrelated negation passes ("Its costs come from stg_orders.order_id, with no other
  inputs." → pass, Appendix D row U14); a statement without a cue ("Nobody is listed as its
  owner.") fails.

**Pass-route reporting (both M9 and M10 v1.2).** Every report shows, per system and view, a
table with one row per field-or-prose rule (interpretation, uncovered part, premise rejection)
and the counts `field` / `prose` / `both` / `neither`, with n. A system without the field shows
only `prose` / `neither` by construction.

**Spurious-field diagnostics (not scored).** Every S4 report shows, per view: (i) the share of
non-multi-part questions whose answer has a non-empty `uncovered_parts`; (ii) the share of
non-false-premise questions whose answer has `premise_corrected = true`. Denominator: answered
predictions of those questions; n shown.

**`eval/metrics.py` change list (1.3.0, implemented only after the owner decides v1.2).**
- `DESIGN_VERSION = "1.2"`, `__version__ = "1.3.0"`.
- `Prediction` gains `uncovered_parts: list[str]` and `interpretation: tuple[str, str] | None`.
- `from_record`: `uncovered_parts` and `premise_corrected` from the view's answer (raw = draft);
  `interpretation` from `final_answer` in every view (ADR 0028). `from_s1_record` unchanged (its
  records have neither field: empty / None).
- New: `content_words(out_of_scope)`, `plain_words(text)` (identifier exclusion),
  `word_matches(token, word)`, `coverage_sentence(sentence, words)`,
  `uncovered_part(pred, gold) -> (bool, route)`, `interpretation_ok(pred, ex, gold) -> (bool,
  route)`, `premise_rejection(...) -> (bucket, route)`; constants `OOS_STOP`, `OOS_SUFFIXES`,
  `COVERAGE_CUES`.
- `score_question`: `interp_ok` from `interpretation_ok`; `uncovered_part_correct` on
  `multi_part`; the premise bucket through `premise_rejection`; routes in `row["diag"]`
  (`route_interpretation`, `route_uncovered`, `route_premise`); spurious-field flags.
- `METRIC_ORDER` gains `uncovered_part_correct`; `summarise` adds `pass_routes` and
  `spurious_fields`; `render_markdown` prints both tables.
- Tests: Appendix D (every row) against the extractor; the S0-gold, S0-linked, S1 v2 and S4
  smoke reports re-score unchanged except the rows below.

**Effect on existing reports (which numbers can move).** Only M9 and M10 rows:
- `uncovered_part_correct` is a **new** row (3 dev questions) in every re-scored report; the
  pass-route and spurious-field tables are new.
- `interpretation_correct`: n/a on dev (0 questions), so nothing moves; its set-metric gate moves
  nothing either.
- `premise_rejected`: unchanged for S0 and S1 (no field); unchanged for the committed S4 smoke
  records (no record sets `premise_corrected`).
- Every other number (node-set F1, trace / impact F1, verdicts, refusal, hallucination,
  citations, path coverage, latency, tokens) re-scores byte-for-byte; a test checks it.

`Decision (owner, 20 Oct 2026, v1.2):` approved as drafted (uncovered-part rule, premise policy,
pass routes, spurious-field diagnostics, the 1.3.0 change list, the effect list).

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

`Decision (owner, 19 Oct 2026):` (a) 0 / 0.5 / 1 per fact, blind sheet, scored by the owner.

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

`Decision (owner, 19 Oct 2026):` (a) as drafted.

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

`Decision (owner, 19 Oct 2026):` CI shown only for n ≥ 10; linker-test flag (b): target **and** yes/no endpoints, 21 questions (the 19 plus dev-74, dev-88). Rest as drafted.

---

## M14. S0 graph oracle

**Question.** What exactly is S0, and what does it return for each type?

**Proposed: two variants, no LLM.**
- **S0-gold:** the gold target (no linker) → the DLens graph → the answer. Upper bound on what the
  engine's graph supports; differences from 1.0 are engine-vs-gold differences.
- **S0-linked:** `resolve_entity` on the question's `mention` (top-1; the code ambiguity policy:
  chain / per candidate / clarification) → the graph. **Hybrid stage off** in S10 (no index build,
  no model download), recorded in the manifest and labelled "S0-linked (hybrid off)" wherever it
  is shown. S0-gold − S0-linked = linker loss. **In any pilot table, the S0-linked row uses the
  same linker configuration (hybrid flag) as the S4 runs in that table**; a table mixing
  configurations is not allowed.
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

`Decision (owner, 19 Oct 2026):` S0-gold + S0-linked as drafted (S10's S0-linked hybrid off, labelled).

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

`Decision (owner, 19 Oct 2026):` as drafted.

---

## M16. The committed pilot table (v0.3 done-when 5)

**Composite F1 definitions** (each is the macro mean of the per-question headline F1 from M1, in
the primary mode from M4):

| Name | Questions in it | n (dev) |
|---|---|---|
| **trace F1** | trace upstream 24 (upstream F1) + computed 11 (inputs F1) + ambiguous **chain** 2 (dev-16, 31: upstream F1 of the gold target; 0 if the M9 chain verdict fails) + multi-part 3 (trace part, upstream F1) + false premise 4 (inputs F1) | **44** |
| **impact F1** | impact downstream 24 (columns F1; dev-64: exposures F1, its `focus`) | **24** |
| **node-set F1 (pooled headline)** | trace F1's 44 + impact F1's 24, one macro mean over 68 questions | **68** |

Not in any F1: ambiguous **clarify** (dev-46, verdict only), yes/no 6 (verdict accuracy), Ask 12
(hand), unanswerable 9 (refusal). 44 + 24 + 1 + 6 + 12 + 9 = 96. The pooled node-set F1 is the
number in the v0.3 resume line ("[X] node-set F1 vs [Y]"); the report always prints its n and
mode next to it. Option: false-premise questions out of trace F1 (n = 40, pooled 64), reported
only through M10.

**Proposed contents.**
- Rows: S0-gold, S0-linked, S1, S4-raw, S4-validated, S4-augmented; panels: qwen3:4b (local),
  Gemini Flash-Lite. The S0-linked row uses the same hybrid flag as that table's S4 runs (M14);
  S10's S0-linked run is hybrid off and labelled so.
- Columns (each with its 95% CI and n): node-set F1 (pooled), trace F1, impact F1, yes/no verdict
  accuracy, refusal accuracy, false-refusal rate, false-premise rejection rate, hallucinated-node
  rate, citation validity (per answer) and coverage, path node coverage, latency p50/p95, tokens
  per question.
- A hop-bucket table (F1 by bucket, one line per system: the headline chart's data).
- S1 vs S4: paired F1 difference with CI, McNemar p.
- Ask: hand rubric means, own table.
- Losses: every question where S4 < S1 listed.
- The metrics-design version and `metrics.py` `__version__`.

`Decision (owner, 19 Oct 2026):` as drafted: pooled node-set F1 over 68 (trace F1 44 including false premise, impact F1 24).

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
- S1 emits refusals and clarifications through the schema fields (`refused`, `clarification`),
  never only in prose (M9).
- Interpretation (M9): the "Interpreted A as B." lead is code-written in S4 only. Before any test
  question with `gold.interpretation` exists (D5b), S11 must state how S1 can satisfy M9's
  interpretation rule; if it cannot, the structured interpretation field (S12, below) becomes
  the rule for every system.

**S12 (agent upgrades):**
- `reach_verdict: yes | no | null` on `Answer` (additive, ADR) (M5), plus a record of **who set
  it** (`llm` or `code`, e.g. when R9 salvage replaces the verdict). S4-raw is scored on the LLM's
  own value only; a code-set value counts only in S4-validated.
- `premise_corrected` (G3) and claim `origin` (G1/G3) (M3, M10).
- A structured uncovered-part field for multi-part questions (G2) (M10).
- A structured interpretation (`{from, to}`) beside the lead sentence (M9); it becomes the M9
  rule for all systems if S11 finds no way for S1 to satisfy the lead-sentence rule.
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

`A`, `B`, `C` stand for dotted ids in the inventory (the tests use real ids). "neg" = removed from
prediction sets; "kept" = stays; "—" = not in the sentence. Rule that decides: pre = cue before
the mention in its clause; post = cue right after the mention; bnd = a clause boundary.

| # | Sentence | A | B | C | Why |
|---|---|---|---|---|---|
| 1 | It comes from A. | kept | — | — | no cue |
| 2 | It does not come from A. | neg | — | — | pre "not" |
| 3 | It doesn't use A. | neg | — | — | pre "n't" |
| 4 | It comes from A, not B. | kept | neg | — | comma breaks post; pre "not" before B only |
| 5 | It does not come from A; it comes from B. | neg | kept | — | `;` bnd |
| 6 | It does not come from A, but from B. | neg | kept | — | "but" bnd |
| 7 | It uses not only A but also B. | kept | kept | — | "not only" is not a cue; "but" bnd |
| 8 | Every column except B is affected, including A. | kept | neg | — | pre "except" for B; "including" bnd before A |
| 9 | All inputs are used except B. | — | neg | — | pre "except" |
| 10 | A is used rather than B. | kept | neg | — | pre "rather than" |
| 11 | A is used instead of B. | kept | neg | — | cue "instead of" is matched before the bnd word "instead" |
| 12 | Neither A nor B is used. | neg | neg | — | pre "neither", "nor" |
| 13 | A no longer feeds B. | neg | neg | — | post "no longer" for A; pre for B |
| 14 | No, A does not reach B. | neg | neg | — | "No," removed; post "does not" for A; pre for B |
| 15 | Yes, A reaches B in 3 hops. | kept | kept | — | "Yes," removed; no cue |
| 16 | It is computed without A. | neg | — | — | pre "without" |
| 17 | B is affected. A is not used in the SQL. | neg | kept | — | post "is not" for A; separate sentence for B |
| 18 | A feeds B, which is not used by the dashboard. | kept | kept | — | comma breaks post for B; the "which" clause is its own clause |
| 19 | A and B; neither is a direct input. | kept | kept | — | cue after both, in the next clause |
| 20 | There is no direct edge from A to B. | neg | neg | — | pre "no" (limit, see notes) |
| 21 | A is not an input to B. | neg | neg | — | post "is not" for A; pre "not" for B (see notes) |
| 22 | A isn't used. | neg | — | — | post "isn't" |
| 23 | A, which is not used by the dashboard, feeds B. | kept | kept | — | comma breaks post for A; the "which" clause does not reach B |
| 24 | A is not aggregated directly; it reaches B through C. | neg | kept | kept | post "is not" for A; `;` bnd |
| 25 | Only A, not B, is used. | kept | neg | — | pre "not" for B |
| 26 | The A column is not used. | neg | — | — | post, after the optional word "column" |
| 27 | A itself does not change. | neg | — | — | post, after the optional word "itself" |
| 28 | A is never null. | kept | — | — | post "is never" voided by the value word "null" |
| 29 | Rows are kept where A is not null. | kept | — | — | post "is not" voided by "null" |
| 30 | A is not null and feeds B. | kept | kept | — | "not" voided by "null" (before the next mention), so it negates neither A nor B |
| 31 | A does not feed B when B is null. | neg | neg | — | "does not" reaches B before "null", so it is not voided (limit for B) |

Notes the owner approves with the rule:
- **Relative clauses (added in this revision, not in the R1 instruction):** ", which / that / who
  … ," is its own clause. Without it, row 23's B would be negated by the "not" inside the
  "which" clause.
- Row 20: a sentence about a missing edge negates both endpoints. Listed so the behaviour is
  known, not hidden.
- Row 21: B is negated too (pre "not"). B is usually the question's target, which M2 already
  excludes from every set, so the effect is small; when B is not the target it is a false
  removal.
- Rows 28–31 (value-word exemption, F1): the owner's wording is "followed within the clause by a
  value word". This draft narrows it to "before the next mention in the clause" so that row 30
  ("A is not null and feeds B") keeps B, and row 31 ("A does not feed B when B is null") still
  negates A. Approved with M3 or changed there.
- A node mentioned once negated and once not is kept. Each report shows, per system, how many
  mentions the rule removed, so the size of these limits is visible.

## Appendix C. Identifier filter test rows (M3 rule 1, M8)

| # | Text | Mentions | In inventory? | Why |
|---|---|---|---|---|
| 1 | e.g. stg_orders.order_id is used | `stg_orders.order_id` | yes | `e.g` is on the stop list |
| 2 | see models/marts/fct_orders.sql | none | — | path removed whole, including `fct_orders` |
| 3 | added in v0.3 | none | — | model part `v0`: not known, no `_`, no dbt prefix |
| 4 | github.com | none | — | model part `github`: not dbt-style |
| 5 | Gemini 3.5 | none | — | `3.5` starts with a digit: not a candidate |
| 6 | i.e. the finance revenue | none | — | stop list |
| 7 | fct_orders.revenue_net | `fct_orders.revenue_net` | no → hallucination candidate | known model, unknown column |
| 8 | fct_returns.return_amount | `fct_returns.return_amount` | no → hallucination candidate (exempt in dev-93, where the question writes it) | `fct_` prefix |
| 9 | model.synthetic_shop.fct_orders.order_id | `fct_orders.order_id` | yes | fully-qualified, cut to two parts |
| 10 | customers.customer_id (a SQL alias quoted in prose) | none | — | `customers`: not a model or seed name, no `_` |
| 11 | rfm_scores.rfm_score (a CTE column quoted in prose) | none | — | `rfm_scores` is on the CTE list: counted as a "CTE reference" |
| 12b | margins_monthly.margin_month (a derived-table column quoted in prose) | `margins_monthly.margin_month` under (a); none under (a+) | no → hallucination candidate under (a); "CTE reference" under (a+) | derived-table alias, not a CTE |
| 12 | payroll.employee_salary | none | — | `payroll`: not dbt-style (exempt in dev-96 anyway) |

Notes:
- Row 10: SQL table aliases without `_` (`orders.`, `items.`, `customers.`) are filtered, which
  keeps quoted SQL from counting as mentions.
- Rows 11 / 12b: the CTE list (M8, F3) takes CTE names out of both the node sets and the
  hallucination count; derived-table aliases join it only under M8 (a+).
- Row 12: a hallucinated id with a plain-word model part (`orders.total`) is not caught. The
  filter trades this for not counting aliases (row 10). It can only undercount hallucinations.

## Appendix D. Field-or-prose test rows (v1.2: M10 uncovered part, M9 interpretation, M10 premise)

Each row becomes one test case of the extractor (Step 2 of S12b). **The expected results are fixed
and are the definition** (owner, STOP 1): if the extractor disagrees with a row, the
implementation stops and the row, expected and actual result go to the owner; neither the row
nor the code is tuned to agree without the owner's decision. "Answered" unless the row says
otherwise. Route: `field` / `prose` / `both` / `neither`; correct = any route but `neither`.

### D.1 Uncovered part (M10), prose branch

Gold texts (dev): **O1** = "who owns it" → content words {`owns`}; **O2** = "how much does it cost
to compute" → {`cost`}. No `uncovered_parts` field in these rows (empty list).

| # | gold | answer text | result | why |
|---|---|---|---|---|
| U1 | O1 | The lineage does not show who owns it. | prose | cue `not` + `owns` |
| U2 | O1 | Ownership is not recorded in the project. | prose | `ownership` = own + "ership"; cue `not` |
| U3 | O1 | I can't tell you the owner of this column. | prose | cue `n't`; `owner` = own + "er" |
| U4 | O1 | The owner is the finance team. | neither | content word, no cue |
| U5 | O1 | This part is not covered by the evidence. | neither | cue, no content word |
| U6 | O1 | It comes from stg_products.product_id. Who owns it is outside what lineage shows. | prose | 2nd sentence: `owns` + `outside` (multi-sentence positive) |
| U7 | O1 | The owner is listed in the YAML. It does not come from stg_orders.order_id. | neither | content word and cue in different sentences |
| U8 | O1 | It uses not only stg_orders.order_id but also owner_id. | neither | `owner_id` is an identifier (excluded); "not only" is not a cue |
| U9 | O2 | The cost to compute it is not available from lineage. | prose | `cost` + `not` |
| U10 | O2 | stg_product_costs.unit_cost is not derived from orders. | neither | both identifiers excluded; no content word left |
| U11 | O2 | unit_cost does not depend on stg_orders.order_id. | neither | `unit_cost` is snake_case (excluded) |
| U12 | O2 | Compute cost cannot be determined from the dbt project. | prose | `cost` + `cannot` |
| U13 | O2 | It is computed from stg_orders.amount and stg_orders.tax, not directly. | neither | `computed` is on the stop list; no content word |
| U14 | O2 | Its costs come from stg_orders.order_id, with no other inputs. | prose | `costs` + `no`: **known false positive** (limit) |
| U15 | O2 | Costs are unknown. | prose | `costs` = cost + "s"; cue `unknown` |
| U16 | O2 | The price of running it is unknown. | neither | synonym, not matched (limit) |
| U17 | O2 | It is not clear what it costs. | prose | `costs` (verb form) + `not` |
| U18 | O1 | No, nobody here knows; the owner is a team decision. | neither | "No," removed; `;` splits; `nobody` is not a cue |
| U19 | O1 | answer_text "Ownership is a separate question." + claim text "It is not in the lineage." | neither | a claim text is its own sentence, never joined to the answer text |
| U20 | O2 | (refused) I can't answer this: the cost is unknown. | neither | not answered |

### D.2 Uncovered part (M10), field branch

| # | gold | `uncovered_parts` | answer text | result | why |
|---|---|---|---|---|---|
| F1 | O1 | ["who owns the column"] | It comes from stg_products.product_id. | field | `owns` in the field; no cue needed |
| F2 | O1 | ["the runtime of the query"] | It comes from stg_products.product_id. | neither | non-empty field, no content word |
| F3 | O1 | ["n/a"] | It comes from stg_products.product_id. | neither | non-empty field, no content word |
| F4 | O2 | ["cost to compute"] | The cost cannot be computed from lineage. | both | field `cost`; prose `cost` + `cannot` |
| F5 | O2 | ["unit_cost"] | It comes from stg_orders.amount. | neither | identifier excluded in the field too |
| F6 | O1 | ["who owns it"] | (refused) I can't answer this. | neither | not answered |

### D.3 Interpretation (M9)

G = the gold `interpretation.column`; H, A = other inventory columns (the tests use real ids).

| # | `interpretation.to` | answer text | result | why |
|---|---|---|---|---|
| I1 | G | It comes from A. | field | field only; G not in the prose |
| I2 | — | Interpreted stg_orders.ordr_total as G. It comes from A. | prose | lead with B = G (B is also a kept mention) |
| I3 | — | Interpreted G as H. H comes from A. | neither | G is the lead's A, which never counts (M3 rule 3) |
| I4 | — | G comes from A. | prose | kept mention |
| I5 | — | G is not used; H comes from A. | prose | post rule not applied in M9; **known limit: predicate negation keeps the identity** |
| I6 | — | It does not come from G. | neither | pre `not` |
| I7 | — | H comes from A, not G. | neither | pre `not` before G |
| I8 | — | G is never null. It comes from A. | prose | post rule not applied (the value-word exemption no longer applies here) |
| I9 | — | Neither G nor H is upstream of A. | neither | pre `neither` / `nor` |
| I10 | — | G feeds H, which is not used by the dashboard. | prose | the relative clause does not reach G |
| I11 | — | H is not G. G comes from A. | prose | negated once, kept once → kept |
| I12 | — | No, G does not reach H. | prose | "No," removed; post-mention rule not applied in M9 |
| I13 | G | (refused) I can't answer this: G is not in the evidence. | neither | not answered (field ignored) |
| I14 | H | Interpreted x as H. It comes from A. | neither | field ≠ G, lead B ≠ G |
| I15 | G | Interpreted x as G. It comes from A. | both | field and lead |
| I16 | — | (clarification listing G and H) | neither | not answered |
| I17 | — | It comes from A, not from G. | neither | pre `not` before G in its clause |
| I18 | — | Yes, G reaches H through A. | prose | "Yes," removed; kept mention |

### D.4 Premise rejection (M10)

P = the premise column (`gold.premise.edge.from`). Case O: P outside the target's closure;
case U: P upstream of it. A, H = other columns.

| # | case | `premise_corrected` | answer text | bucket | route | why |
|---|---|---|---|---|---|---|
| P1 | O | true | The answer does not use P. | rejected | both | field (P not kept) + negated mention |
| P2 | O | true | P feeds the target directly. | asserted | neither | a kept P voids the field branch in case O |
| P3 | O | true | It comes from A and H. | rejected | field | P silent; field holds |
| P4 | U | true | P reaches the target through A, not directly. | rejected | field | case U: a kept P is context; the `not` comes after P |
| P5 | U | false | It does not come directly from P. | rejected | prose | negated mention |
| P6 | O | true | (refused) I can't answer this. | silent | neither | not answered |
| P7 | O | false | P is used. | asserted | neither | kept mention, no field |

---

## Change log
- 19 Oct 2026: first draft (S10 step 1), version 1.0-draft. Every Decision PENDING.
- 19 Oct 2026: pre-decision revisions (owner R1–R10), still 1.0-draft, every Decision PENDING.
  M3: post-mention negation cue, "including" / "plus" boundaries, relative clauses as their own
  clause (Claude Code's addition, flagged in Appendix B); identifier filter with stop list and
  path removal (new Appendix C). M1: strict vs closure-tolerant inputs F1. M10: case O / case U
  per false-premise question. M7: option (iv) by edge kind, with the indirect-citation evidence
  from the graph. M9: chain headline from prose; clarify / refusal from schema fields. M14 / M16:
  S0-linked uses the S4 runs' hybrid flag; pooled node-set F1, trace F1 and impact F1 defined.
  §18: reach_verdict setter, S1 refusals / clarifications via fields, interpretation for S1.
  No S1 or S4 result added.
- 19 Oct 2026: negation value-word exemption, CTE guards (owner F1–F3; relative-clause rule and
  R1–R10 approved), still 1.0-draft. M3: value-word exemption, narrowed to "before the next
  mention" (flagged; Appendix B rows 28–31). M7: (iv-k) guard checked by metrics itself; finding:
  the 23 key-only citations use derived-table aliases, so option (iv-k+) is added. M8: CTE-name
  list from a plain regex over the corpus SQL, its own diagnostic; option (a+) adds derived-table
  aliases; plain-word model-part gap documented as an undercount.
- 19 Oct 2026: **version 1.0.** Every Decision set by the owner in four multiple-choice rounds.
  Differences from the recommendations: M7 takes (iv-k+) (derived-table aliases, with the
  cast-alias test); M8 takes (a+); M13's linker-test flag covers 21 questions (target and yes/no
  endpoints).
- 19 Oct 2026 (Step 2, implementation, before any result was read):
  - **Metric bug fixed:** dev-46 (clarify) carries a gold `paths` list, so path node coverage
    scored a correct clarification 0. Path node coverage now applies only to questions whose
    gold verdict is not `clarify` (M6). Found by the identity test; regression test added.
  - **Clarification, no change to the approved mapping:** M4 (a)'s text sends "no cue, or cues
    of both classes" to the family; the approved Appendix A also resolves dev-50 (an effect cue
    on a false-premise question) by family. `eval/metrics.py` implements Appendix A: the
    family fixes the mode; a cue that contradicts the family is recorded only.
  - **Reading noted:** M8's denominator counts the question's own ids (only the numerator exempts
    them). metrics.py parses YAML with PyYAML (dev dependency); `dlens.gold_spec` reads no files.
- 19 Oct 2026 (Step 4, S0 scoring): **reporting bug fixed** — a valid `star` citation was listed
  under an answer's invalid-citation reasons (its label lacked the "ok" prefix). No metric value
  changed (validity was already counted correctly). Test added. metrics.py 1.0.1.
- 19 Oct 2026: **version 1.1** (owner decisions on the three S10 questions; metrics.py 1.1.0).
  - **M7 per-answer citation validity:** an answer whose own structured `reach_verdict` is "no"
    and that has zero file citations is n/a, not invalid; with citations it is checked as usual;
    the system's verdict decides, never the gold. Rationale: spec §0 row 27, a correct "No" has
    nothing to cite. Seen in S0-gold's per-answer validity 0.959 (3 of 74 answers: dev-10, 75, 76,
    all correct "No" verdicts) before any S4 number was read.
  - **M9 clarify:** correct if a clarification lists every gold candidate **or** the answer is
    answered and every gold candidate is a non-negated mention. Both behaviours are correct for a
    genuinely ambiguous question; answering only one candidate is the failure. No change to
    dev.jsonl gold or to spec §8 (which answers per candidate for ≤ 3 tied candidates).
  - **R3 disagreement count (bug fix):** counts only ids the R3 check actually ran on (ledger ids
    of a record whose validation ran). Found in Step 5, diagnostic only, no headline value changes.
- 20 Oct 2026 (S11): **S1 records supported** (metrics.py 1.2.0; no definition change, this
  document stays v1.1). An S1 adapter (`from_s1_record`: validated view only, no edge citations)
  and the M5 verdict accessor reading the ADR 0024 `Answer` fields (`reach_verdict`,
  `reach_verdict_source`) and S0's record-level key; the nested `{value, set_by}` shape guessed in
  S10 is no longer read (no committed record used it). S0 reports re-score byte for byte.
- 20 Oct 2026 (S12b step 1): **version 1.2 DRAFT** (not decided; metrics.py stays 1.2.0). The
  s12-design B2 + B5 policy (structured field **or** deterministic prose, one rule for every
  system), with the owner's plan amendments: M9 interpretation (field / lead / kept mention; M3
  rules 3–4 reused exactly; all three views count the code-set field, ADR 0028); M10 uncovered
  part (new row: field with a content word, or a sentence with a content word and a coverage
  cue; fixed stop list, suffix rule, identifier exclusion); M10 premise correction (v1.1 rule
  restated; the field branch requires answered and, in case O, no kept mention of the premise);
  pass-route tables; spurious-field diagnostics for S4; the metrics.py 1.3.0 change list and the
  effect on existing reports (M9 / M10 rows only). New Appendix D (C was already the identifier
  filter rows). No S1 or S4 result read.
- 20 Oct 2026 (S12b STOP 1): **version 1.2 approved (implementation pending).** One owner change
  to the draft: M9's prose-mention branch applies only pre-mention negation (clause rules,
  pre-cues, "Yes,/No," removal, any kept mention keeps G); the post-mention rule and the
  value-word exemption do not apply there. Reason: the post-mention rule negates a statement
  *about* the column, while M9 asks which column the answer understood; a correct "No, G does not
  reach H" must not fail M9, and that case hits S1 hardest because S1 has only the prose branch
  (rule 12). Scope: that branch only (M3 node sets, the M9 v1.1 clarify rule and M10 premise keep
  the full rule). Appendix D.3: I5, I8, I12 → prose (I5 a stated limit); I17, I18 added. Appendix
  D's expected results are fixed: a disagreeing row stops the implementation for an owner
  decision.
- 21 Oct 2026 (S12b step 3): **version 1.2 Accepted**; metrics.py 1.3.0 implements it (all 51
  Appendix D rows pass on the first run, no row or rule tuned). The committed S0-gold, S0-linked,
  S1 v2 and S4 smoke reports re-score with only the v1.2 additions (new rows, tables and
  diagnostics; no existing value changed or removed), checked by `test_report_regression.py`.
