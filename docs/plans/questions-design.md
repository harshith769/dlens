# Dev questions design (S09, v0.3 D5a)

**Status:** draft, 18 Oct 2026. The owner's answers to the S09 plan questions (18 Oct 2026) are
built in. **Nothing is generated until the owner approves this document.**
**Inputs:** spec §11.2, DESIGN_v2 §3 and §8 (amended here, §10), `lineage_spec.yml`, `traps.yml`,
`dlens.gold_spec`, the 20 questions in `eval/questions/dev.jsonl`, `linker-design.md`.
**Output:** 96 dev questions in `eval/questions/dev.jsonl`, written only after every question has
an owner decision (§8).

Rules that hold throughout:
- Gold comes only from `lineage_spec.yml` (plus `traps.yml` and `exposures.yml` for tags and
  dashboards), computed through `dlens.gold_spec`. It never comes from parser output, the graph,
  or the linker.
- S09 generates questions from the dev pool only. It never prints or writes a test-pool question.
  The test pool exists only as a column → split list (§2).
- No cloud LLM is used. Paraphrases come from local qwen3:4b through `LLMClient` (§6).
- `test.jsonl`, `external.jsonl` and their `.sha256` files are never touched.

---

## 1. Count table (dev 96)

Spec §11.2 parent totals are unchanged: Trace 45, Impact 30, Ask 12, Unanswerable 9.
**Owner Q1:** how-computed questions are code-scored on their direct-input set, so they count under
Trace. dev-11, 12 and 13 are re-tagged `type: trace, subtype: computed`. Ask holds meaning
questions only, all scored by hand in the pilot (D4).

| Row | Parent | Dev | Subtypes | Existing |
|---|---|---|---|---|
| Trace 1 hop | Trace | 8 | upstream 3 · computed 4 · multi-part 1 | dev-01, 02, 11, 12, 13 |
| Trace 2–3 | Trace | 11 | upstream 6 · computed 3 · ambiguous 1 · multi-part 1 | dev-03, 04, 14, 20 |
| Trace 4–5 | Trace | 11 | upstream 7 · computed 2 · ambiguous 1 · multi-part 1 | dev-05, 16 |
| Trace 6+ | Trace | 11 | upstream 8 · computed 2 · ambiguous 1 | dev-06, 15 |
| False premise | Trace | 4 | 2 targets at 1–3 hops · 2 at 4+ | dev-17, 18 |
| Impact (downstream set) | Impact | 24 | downstream depth 1: 6 · 2–3: 6 · 4–5: 5 · 6+: 5 · indirect-only source: 2 | dev-07, 08, 09 |
| Yes/no reachability | Impact | 6 | 3 yes / 3 no (direct+indirect); ≥ 1 is "no" direct-only but "yes" with indirect edges | dev-10 |
| Ask (meaning) | Ask | 12 | revenue definitions 3 · stale doc 1 · grain / near-duplicate 2 · CASE meaning 2 · star exclusion 1 · doc injection 0–1 · other semantics 2–3 | — |
| Unanswerable | Unanswerable | 9 | dotted near-miss 4 (incl. `int_order_shipping.shipping_cost`) · bare non-existent 2 · typo in a dotted id 1 · unknown model 1 · out of domain 1 | dev-19 |
| **Total** | | **96** | Trace 45 · Impact 30 · Ask 12 · Unanswerable 9 | 20 |

Subtype totals: upstream 24, computed 11, ambiguous 3, multi-part 3, false premise 4, impact 24,
yes/no 6, ask 12, unanswerable 9.

The 6+ bucket must include at least 3 targets at 8–10 hops (for example on the RFM / segment and
marketing paths), drawn from the dev pool.

### 1.1 Wording mix (owner amendment 1)

| Label | Meaning |
|---|---|
| `identifier` | The template names the target as `model.column`. |
| `name_words` | The mention is built mechanically from the column's name words (`previous_order_date` → "previous order date"). When the bare name exists in more than one model and the question is not an ambiguity question, the model's name words are added ("order count in daily revenue"). |
| `description` | The mention comes from the column's YAML `description` (project text, never gold), lightly turned into a noun phrase. |
| `paraphrase` | A local qwen3:4b rewrite of the template text. The template form is kept in `template_question`. |

| Row | identifier | name_words | description | paraphrase | Total |
|---|---|---|---|---|---|
| Trace 1 | 5 | 1 | 1 | 1 | 8 |
| Trace 2–3 | 5 | 2 | 2 | 2 | 11 |
| Trace 4–5 | 5 | 2 | 1 | 3 | 11 |
| Trace 6+ | 5 | 2 | 1 | 3 | 11 |
| False premise | 3 | 0 | 0 | 1 | 4 |
| Impact | 12 | 4 | 3 | 5 | 24 |
| Yes/no | 3 | 1 | 0 | 2 | 6 |
| Ask | 4 | 4 | 2 | 2 | 12 |
| Unanswerable | 6 | 2 | 0 | 1 | 9 |
| **Total** | **48** | **18** | **10** | **20** | **96** |

Re-labels of the existing 20: the 17 identifier questions stay `identifier`. dev-14 ("prod category
on order items") and dev-16 ("previous order date") become `name_words`. dev-15 ("number of orders
per customer") is a hand paraphrase, so it becomes `paraphrase` with `source: v0.2`. All three
re-labels are flagged for review.

Description wording rules. A description is used only if it:
- identifies one column (no other column has the same description text; "Order key." and the
  other key descriptions are out);
- has ≥ 4 content words;
- for trace and computed questions, does not name the target's inputs (for example
  `dim_customers.lifetime_value`, "Items subtotal plus tax minus refunds…", gives away the answer,
  so it is used only for impact or Ask);
- is not a stale-doc or doc-injection text (those docs are wrong on purpose; they are tested by
  Ask).

113 model columns have a description; about 10 are needed.

### 1.2 Trap coverage (dev)

Each of the 9 traps gets ≥ 2 dev questions, counted per question (owner Q5). Trap tags come from
`traps.yml` (the source of truth), never from the spec's informational `traps:` tags.

| Trap | Column supply (`traps.yml`) | Dev questions planned | How |
|---|---|---|---|
| rename_chain | 4 chain columns (2 instances) | ≥ 2 | trace from the last name, impact from the first |
| select_star | 23 star columns | ≥ 3 | trace through the star; impact on `int_order_profit.is_profitable` if that column is in dev |
| two_revenue_definitions | 10 | ≥ 4 | Ask, false premise, yes/no (`sales_tax` → `roas` yes, `refund_amount` → `roas` no, if in dev) |
| deep_chain | 55 columns at 6+ | 11 + impact | the trace 6+ row and deep impact sources |
| join_key_only | 4 keys | ≥ 2 | impact on an indirect-only source; one yes/no that is yes only with indirect edges |
| fan_in_aggregate | 3 | ≥ 2 | trace or computed (all inputs must be cited) |
| stale_doc | 2 | ≥ 2 on 1 column | Ask on the dev column, plus a trace or impact on the same column |
| near_duplicate_names | 12 (+ near-miss names) | ≥ 3 | trace or impact on a near-duplicate, plus the dotted near-miss |
| exposures | model-level (4 marts, 2 dashboards) | ≥ 3 | impact questions whose gold includes a dashboard; ≥ 1 that reaches one dashboard only |

`doc_injection` (not a trap): one column, placed by the pool hash. If it lands in dev, one Ask
question uses it.

**Amendment to DESIGN_v2 §8 (owner Q5).** DESIGN_v2 §8 asks for ≥ 2 dev and ≥ 4 test questions per
trap on different columns. stale_doc has 2 columns, doc_injection has 1, and exposures are
model-level. Under the column split (§2) the test side of stale_doc gets one column, so its ≥ 4 test
questions cannot be on 4 distinct columns. They are counted per question (Ask + trace + impact on
the same column, which D5 allows because D5 limits only trace and impact). D5b reports exactly
which traps fall short in test.

---

## 2. Column pools (before any question is generated)

`scripts/question_pools.py` writes `eval/questions/pools.yml`. It is deterministic, and reruns give
the same file byte for byte.

- **Candidates:** every column in `lineage_spec.yml`: 84 seed columns and 318 model columns.
  Non-existent columns (unanswerable questions) use no supply.
- **Stratum** = (hop bucket, rarest trap):
  - hop bucket: `1`, `2-3`, `4-5`, `6+`, `seed` (depth 0) or `n/a` (`session_number`);
  - rarest trap: the trap with the fewest columns among those that name the column (the 8
    column-level traps plus `doc_injection`), or `none`. A trap "names" a column when the column is
    in its `columns`, is the `to` end of one of its `edges`, or is the first or last column of one
    of its `paths`.
- **Ordering:** inside each stratum, columns are sorted by `sha256("s09-pools-v1:" + column_id)`.
- **Forced dev:** the 19 existing targets (dev-19's target does not exist) go to dev first and
  count toward their stratum's dev quota.
- **Dev quota** per stratum = `max(forced, round(0.30 × n))`, and at least 1 when `n ≥ 2`.
  - `n = 1`: dev when the hash's first 8 hex digits / 2³² < 0.30.
  - Strata of size 2 split 1/1.
  - The rest of each stratum goes to test.
- **File contents:** `{salt, share, columns: {id: {split, stratum}}}` and a per-stratum summary.
  It lists column ids only and holds no question text for either split.
- **Checks (unit tests):** deterministic; dev ∩ test = ∅; all 19 forced columns in dev; every
  stratum's quota met; with the expected share, the dev pool covers the count table (≥ 11 targets
  in each trace bucket, ≥ 3 at 8–10 hops, ≥ 24 impact sources by downstream bucket, and the trap
  minimums of §1.2). If a requirement is short, the script fails and names the stratum. **It never
  borrows a test column.**

Supply, from the spec: trace buckets 1: 74, 2–3: 133, 4–5: 55, 6+: 55, n/a: 1. Downstream depth
(direct edges) 1: 90, 2–3: 108, 4–5: 30, 6+: 26, plus 19 sources whose only downstream use is
through indirect edges. At 30%, about 120 columns go to dev, about 17 of them in each of 4–5 and 6+.

The linker split is unchanged (owner Q2). `scripts/gen_linker_cases.py` is pinned to the original
20 dev targets (a frozen list in the script), so linker-dev and linker-test cases don't move.
`eval/linker/dev_mentions.jsonl` is built from all 96 questions, using each question's worded
mention. The S09 report gives how many of the 96 targets are linker-test gold columns.

---

## 3. Selection inside the dev pool

`scripts/gen_dev_questions.py` takes targets from the dev pool only (a hard assert, plus a test).
For each row of §1, in a fixed order, it walks the row's candidate columns in hash order and takes
the first that meet the row's rule, the D5 limit (≤ 1 trace and ≤ 1 impact question per column)
and the trap minimums. The 20 existing questions are placed first.

| Row | Candidate rule |
|---|---|
| Trace upstream / computed | target's hop bucket equals the row. Computed: the target has ≥ 1 TRANSFORMATION or AGGREGATION input edge. Upstream: any. |
| Ambiguous | the bare column name occurs in ≥ 2 models, and those columns lie on one chain (chain policy, as dev-16) or on different branches (clarification); the target is the most downstream candidate |
| Multi-part | an in-scope trace part plus one out-of-scope part from a fixed list ("can I drop it?", "who owns it?", "how often is it refreshed?") |
| False premise | the target's trace slot. The premise names a plausible column that is **not** upstream of the target in either mode (a sibling, a near-duplicate, or the other revenue definition) |
| Impact | the source's downstream depth equals the row's bucket; indirect-only sources from the §4 list of DESIGN_v2 |
| Yes/no | a (source, target) pair. Verdicts and the direct-vs-indirect case are planned in §1 |
| Ask | hand-drafted from DESIGN_v2 / `traps.yml` text (below) |
| Unanswerable | hand-listed near-misses checked against the spec inventory (the column must not exist) |

Spare candidates: the generator also emits up to 2 spare questions per row from the dev pool. A
spare is used only when the owner drops a question (§8).

**RFM path wording (owner point 3).** `rfm_monetary_score` feeds `customer_segment` in the lineage,
but by construction it can never change the segment's value. Questions on the RFM / segment path
are therefore worded as lineage, not value impact: "Which columns are downstream of X in the
lineage?" and "Is Y downstream of X?", never "what changes if X changes?". The generator applies
this to every impact or yes/no question whose source or target is a `dim_customer_rfm`,
`dim_customer_segments`, `fct_segment_monthly` or `fct_customer_leaderboard` column, or whose path
runs through one.

**Ask questions (12)** are drafted by Claude Code from design text and approved by the owner, as
spec §11.2 says ("hand-written"). Gold is a rubric of required facts, each fact citing its source
line (`DESIGN_v2.md:NN` or `traps.yml:NN`). Examples:
- "Is ROAS based on finance revenue?" → no; marketing revenue (items subtotal plus tax). Source:
  `traps.yml` two_revenue_definitions.
- The dev stale-doc column, for example "Does fct_order_margins.contribution_margin subtract
  discounts?" → yes, the SQL does; the YAML says otherwise. Which of the two stale-doc columns is
  used depends on the pool.

---

## 4. Templates

Fixed templates, one per (subtype, wording). `{t}` is the mention: an identifier or name words.

| Subtype | Template |
|---|---|
| upstream | "Where does {t} come from?" |
| computed | "How is {t} computed?" |
| ambiguous | "Where does {t} come from?" (bare name words) |
| multi-part | "Where does {t} come from, and {out_of_scope}?" |
| false premise | "Why does {t} include {premise_column}?" or "Why is {premise_column} used directly in {t}?" |
| impact | "What is affected if {t} changes?"; RFM path: "Which columns are downstream of {t} in the lineage?"; exposures: "Which dashboards are affected if {t} changes?" (≥ 1 question) |
| yes/no | "If {s} changes, does it affect {t}?"; RFM path: "Is {t} downstream of {s} in the lineage?" |
| unanswerable | the impact or upstream template on the near-miss id |

---

## 5. Gold format

Every question keeps the existing fields (`id, corpus, split, type, subtype, question, target,
hop_depth, hop_bucket, wording, traps, gold, expect, source_lines`). New fields:
- `source`: `v0.2`, `template` or `hand`;
- `template_question`: the template text, when `wording` is `paraphrase`;
- `mention`: the worded entity text, used by `dev_mentions.jsonl`;
- `stratum`: the pool stratum;
- `review_flags`: list.

`gold` (everything computed with `dlens.gold_spec` from `lineage_spec.yml`):

| Field | Used by | Content |
|---|---|---|
| `verdict` | all | `answered`, `refused`, `chain`, `clarify`, `partial` (multi-part) |
| `edges` | trace, impact, yes/no | the direct edges of the answer subgraph, `{from, to, kind, line}`; `line` = the edge's line in v2 `lineage_spec.yml` (kept for `dev_report` compatibility) |
| `inputs` | trace, computed | `{direct: [...], indirect: [{from, type}]}`: the target's one-hop inputs |
| `upstream` | trace | `{direct: [...], all: [...]}`: closures over direct edges, and over direct + indirect |
| `sources` | trace | seed columns in the direct closure |
| `paths` | trace | the longest seed → target direct path(s), ties broken by name (path exact match is defined in S10) |
| `downstream` | impact | `{direct: [...], all: [...]}`, plus `models: {direct, all}` and `exposures: {direct, all}` |
| `reach` | yes/no | `{from, to, direct: yes/no, all: yes/no, path: [...]}` (the path only when the answer is yes) |
| `premise` | false premise | `{edge: {from, to}, holds: {direct: false, all: false}}` plus the correct inputs |
| `candidates` | ambiguous | every spec column whose bare name matches the mention (from the spec inventory, not the linker) |
| `out_of_scope` | multi-part | the part the tools cannot answer |
| `facts` | Ask | rubric facts, each with a source line |
| `closest` | unanswerable | informational: nearest spec names by edit distance on the bare name. Not scored until S10 decides |
| `interpretation` | dotted near-miss resolved under the trap-8 policy | `{text, column}` (§7) |

Both direct-only and direct + indirect sets are stored wherever they differ. Which one is scored
is decided in S10 (`metrics-design.md`, owner).

`expect` keeps the v0.2 shape (`verdict`, `must_cite`, `forbid_edges`, `or_refused`, `modes_ok`,
`yes_no`) so that `scripts/dev_report.py` (the dev-only smoke scorer, not the benchmark metric)
can run on all 96. For new questions it is derived from `gold`:
- trace: `must_cite` = each direct input edge;
- impact: one group per first-hop downstream edge;
- yes/no: `yes_no`;
- refused / clarify: verdict only.

`dev_report` gets only the changes needed to run on the new subtypes. Anything it can't score is
reported as `n/a`, never forced.

**The existing 20 (owner Q3).** id, target, question text and `expect` are kept. `gold` is
regenerated from v2. Their current gold is v1-era: line numbers into the v1 file, and v1 downstream
sets (dev-07 has 1 edge). Every difference between old and new gold is a review flag
(`gold_changed: …`). The S09 report re-scores S08's dev-mention linker result (v1 vs v2) on the
regenerated v2 gold, and states that S08's 19/20 was measured on stale v1 gold.

---

## 6. Paraphrases (local only)

`scripts/paraphrase_questions.py` runs on the 20 questions labelled `paraphrase` that come from
templates (dev-15 is already one).
- **Model:** qwen3:4b-instruct-2507-q4_K_M via `LLMClient` (`DLENS_PROVIDER=ollama`, cache in
  `eval/cache`). No cloud provider is accepted. The script refuses unless the provider is ollama.
- **Input:** the template question text only. It never sees gold, the target field, the type or
  the corpus.
- **Prompt:** "Rewrite this question in different words. Keep every identifier written like
  `name.name` exactly as written. Do not add or remove information. Reply with the question only."
  It is sent with 3 fixed style hints (plain, short, conversational), so there are 3 candidates.
  The cache makes reruns free and identical.
- **Automatic flags** (any flag means the candidate is not auto-picked):

| Flag | Rule |
|---|---|
| `id_dropped` | a dotted id in the template is not verbatim in the candidate |
| `id_added` | the candidate has a dotted id or snake_case name not in the template |
| `entity_changed` | for name-words templates: a content token of the mention (normalised: case, plural, the linker abbreviation table) is missing |
| `intent_changed` | the intent class differs: trace (come from / source / origin / derived / feed), computed (computed / calculated / formula / how is), impact (affect / impact / break / downstream / depend), yes/no (starts with an auxiliary verb, or "if …, does …") |
| `part_dropped` | multi-part: the out-of-scope part's key words are missing |
| `premise_dropped` | false premise: the premise column is missing |
| `length` | candidate / template length ratio outside 0.6–2.0 |
| `format` | more than one line, more than one question mark (single-part questions), quotes or commentary |

- **Pick:** the first unflagged candidate in style order. If all 3 are flagged, the question keeps
  its template text, is flagged `no_clean_paraphrase`, and the owner decides (fix with new text,
  or accept the template as `name_words` / `identifier`).
- **Report:** every candidate and its flags go to `eval/questions/review/paraphrases.md`. Flagged
  items are listed first in the review.

---

## 7. shipping_cost (linker_gaps `conflicts_s09`): decided by the owner

**How the DESIGN_v2 near-miss question would read:** "What is affected if
stg_shipments.shipping_cost changes?" (trap 8 lists `shipping_cost` as an unanswerable near-miss).

**What the current linker does** (probed read-only on 18 Oct 2026, no LLM):

| Text | resolve_entity | Agent loop |
|---|---|---|
| `stg_shipments.shipping_cost` | `stg_shipments.shipping_cost_usd`, normalised 0.87, not ambiguous, note "interpreted … as …" | answers, with "Interpreted … as …" in front (amendment C.4) |
| `int_order_shipping.shipping_cost` | no match (that model has `shipping_cost_total`) | refuses, 0 LLM calls |
| `fct_order_margins.shipping_cost` | no match | refuses, 0 LLM calls |
| `shipping cost` (bare) | 4 candidates, ambiguous | asks for clarification |

**Decision (owner, 18 Oct 2026): option (b), an explicit policy.**
- DESIGN_v2 trap 8 gains: *"A dotted near-miss that only omits a unit the real column has is
  interpreted visibly ('Interpreted ... as ...'); any other near-miss must be refused."*
- The dev near-miss question uses `int_order_shipping.shipping_cost` (gold: refused).
- lk-no_match-026 is re-golded to `[stg_shipments.shipping_cost_usd]` (interpreted), with a note
  that the change followed a seen linker-test result. The item leaves `conflicts_s09`. This is an
  own commit, after this document is approved.
- **Note for S10:** an interpreted answer counts as correct only if the interpretation note
  appears in the answer.
- A question whose dotted id is interpreted under this policy has `gold.interpretation` and
  `verdict: answered`. None is planned in dev beyond what the pool brings, and any that is used is
  flagged for review.

---

## 8. Review workflow

1. The generator and paraphraser write `eval/questions/review/dev_candidates.jsonl` (96 plus
   spares). `eval/questions/dev.jsonl` is not touched until step 4.
2. `eval/questions/review/dev_review.md`: one row per question, flagged rows first. Columns: id,
   type/subtype, strata (hop bucket, traps, wording), question, target, gold summary (counts and
   the first items), flags.
3. `eval/questions/review/dev_decisions.yml`: `{id: {decision: pending}}` for every question. The
   owner sets each to:
   - `accept`;
   - `fix` with `text:` (new question text; the gold does not change unless the owner also notes
     a target change, and then it is regenerated);
   - `drop` (the next spare of the same row takes its place, and gets its own entry).
4. `scripts/check_review.py` (`make check-review`) fails unless:
   - every decision is set;
   - every `fix` has text;
   - every drop is replaced by an accepted spare;
   - the final counts equal §1 and §1.1 (wording shifts from fixes are shown, and allowed only if
     the owner re-labels).

   Only then does `scripts/apply_review.py` write `eval/questions/dev.jsonl` (96).
5. After that: regenerate `dev_mentions.jsonl`, then re-run `scripts/linker_report.py`,
   `scripts/retrieval_sanity.py` and `make eval-smoke` (Ollama, cached runs reused). Report only, no
   tuning.

---

## 9. Implementation steps (after approval; one commit each)

2. shipping_cost data change: re-gold lk-no_match-026 in `variants.yml`, regenerate the linker
   cases, remove the `conflicts_s09` entry.
3. Move the gold helpers into `dlens.gold_spec` (view, depths, closures, paths, exposures). The
   checker imports them. Tests; `docs/explain/gold-spec.md`.
4. Column pools (§2) and tests.
5. Generator (§3–§5), `docs/explain/questions.md`, tests. Also pin `gen_linker_cases.py` to the 20.
6. Paraphraser (§6) with a fake-client test. Then a local Ollama run.
7. Review files and `check_review.py` / `apply_review.py`. **Stop for the owner's review.**
8. After the review: apply, `dev.jsonl` (96), the reports, the S09 report.

## 10. Amendments to DESIGN_v2 made by this document
- Trap 8: the dotted near-miss policy (§7), written into DESIGN_v2 §3.
- §8: how-computed questions count under Trace (owner Q1). Small-trap test coverage is counted per
  question and cannot reach 4 distinct columns (owner Q5). The type-mix table there is superseded
  by §1 here.

## Change log
- 18 Oct 2026: first draft (S09 step 1), with the owner's answers to the plan questions.
