# Entity linker v2: design (S08, v0.3 B2)

Status: **draft for owner approval** (17 Oct 2026). No code until it is approved.
Scope: `resolve_entity` in `src/dlens/agent/tools/entity.py`, a new `Toolbox(index=...)`
argument, the linker test set under `eval/linker/` and a linker report. The lineage engine,
`eval/metrics.py`, the validator rules and the agent loop's refusal and ambiguity code are not
touched. The loop keeps importing `AMBIGUOUS_GAP`.

Inputs: spec §8 (entity linker, ambiguity policy), the owner's answers of 17 Oct 2026 (in the
S08 plan), `corpora/synthetic_shop/linker_gaps.yml`, `eval/reports/retrieval-sanity.md`.

---

## 1. What is wrong with v1 (the evidence)

| # | Symptom | Cause in v1 code |
|---|---|---|
| G1 | 3 exact column ids are not top-1 (`dim_customer_segments.customer_segment` rank 4, `fct_customer_cohorts.cohort_customers` rank 2, `fct_monthly_finance.finance_month` rank 2) | Exact matches and fuzzy matches share one score scale, and `_soft_dice` is **unbounded**: each query token adds its best match, so repeated tokens (`customer … customer`) push the total above 1.0. A model name then scores 1.068 against the exact id's 1.0. |
| G2 | "lifetime value" → `dim_customers.lifetime_value` wins only on tie-break order against `fct_customer_leaderboard.lifetime_value_usd` (both 0.93) | Dropping the weak token `usd` has the same score as an exact token match. |
| G3 | dev-15 "number of orders per customer" → 5 mixed fuzzy candidates, so the agent asks for clarification | Nothing maps "number of X" to `X count`, and the words "per customer" only add noise. Hybrid search doesn't save it either: the `dim_customers.order_count` card is `dim_customers.order_count / type: BIGINT` (no YAML description), and its rank is "–" in bm25, dense and hybrid (retrieval-sanity.md). |
| G4 | No no-match: everything ≥ 0.30 is a candidate | `MIN_SCORE = 0.30` is a display floor, not a decision. |

## 2. Stages

Each candidate carries `stage` (1, 2 or 3), `tier` (below) and its score parts.

### Stage 1: exact
| tier | rule | score |
|---|---|---|
| `exact_id` | the text equals a unique id, a `model.column` id or a model name (case-insensitive, trimmed) | 1.00 |
| `exact_name` | the text equals a column name literally (`refund_amt`); every column with that name gets it | 0.97 |

**Ranking rule (owner amendment):** stage-1 candidates are always ranked above everything else
(lexicographic on stage), so an exact match is always top-1. Inside stage 1 the order is score,
then the tie-break (§3.4). This rule fixes G1 directly, whatever the scorer does.

### Stage 2: normalised
The text and every column name go through one normaliser:
1. **Surface normalisation:** lower case; split on `_ . - space` and camelCase; strip a plural
   `s` (length > 3, not `ss`; as in v1); drop stopwords (§2.3) from the text only.
2. **Rewrites:** the abbreviation table (§2.1), the phrase rules (§2.2), dropping weak tokens
   (`usd`), and comparing tokens as a multiset (word order).

| tier | rule | score |
|---|---|---|
| `surface` | token sequence equal after step 1 alone (`refund amount` = `refund_amount`, `OrderDate` = `order_date`) | 0.93 |
| `rewritten` | equal after step 2 (any number of rewrites: `refund amt`→`refund_amount` via amt, `amount refund` by word order, `lifetime value` = `lifetime_value_usd` without usd, `number of orders` = `order_count`) | 0.87 |
| `fuzzy` | bounded token similarity (§3.1), on rewritten tokens | ≤ 0.80 |

`model.column` and "column of/on/in model" text: when the model part names a real model, the
column part is matched only against that model's columns. A dotted text whose model exists but
whose column part reaches no `surface` or `rewritten` match in that model gives **no-match**
(§4.1), the same decision the loop's `_unknown_column` makes before the tool phase. Typos inside
a dotted id are therefore no-match, which matches today's loop behaviour (it refuses them).

Models are candidates too, as in v1: an exact name is stage 1, a surface or rewritten name is
0.93 or 0.87, and a fuzzy name is ≤ 0.72 (0.9 × the column bound, as in v1). Stage 3 never
returns models: the cards are column cards.

#### 2.1 Abbreviation table (every entry for approval)
One canonical token per abbreviation. It applies to both sides, so `amt` in a column name and
"amount" in the text meet at `amount`. Column: **keep** (in v1, still justified), **add** (new),
**drop** (in v1, removed).

| abbreviation | canonical | action | evidence / reason |
|---|---|---|---|
| amt | amount | keep | `raw_payments.amt`, `refund_amt` (trap 8) |
| qty | quantity | keep | `qty_on_hand` ×5 in the spec |
| cust | customer | keep | common dbt shorthand |
| prod | product | keep | dev-14 wording ("prod category") |
| num | number | keep | common shorthand; only used as a word, never rewritten to count (§2.2) |
| ts | timestamp | keep | dbt `_ts` convention |
| dt | date | keep | dbt `_dt` convention |
| desc | description | keep | common shorthand |
| cat | category | keep | common shorthand |
| addr | address | keep | common shorthand |
| pmt | payment | keep | common shorthand |
| txn | transaction | keep | common shorthand |
| avg | average | keep | `avg_*` in the spec |
| tot | total | keep | common shorthand |
| pct | percent | **add** | `discount_pct` ×4 in the spec |
| percentage | percent | **add** | so "discount percentage" meets `discount_pct` |
| promo | promotion | **add** | `promo_*` ×3 in the spec |
| rev | revenue | **add** | common shorthand; `revenue` ×14 |
| custs | customer | **drop** | redundant: plural stripping turns it into `cust` |
| no | number | **drop** | collides with the English word "no" ("does X have no …") |
| ref | refund | **drop** | it usually means "reference"; `refund_amt` is reached through `amt` |
| tx | transaction | **drop** | no corpus use; `txn` covers it |

Not expanded on purpose: `usd` (a weak token, below), `utm`, `roas`, `rfm`, `cogs`, `mom`. These
are names in their own right, and expanding them would only add false matches. `usd` stays a
**weak token**: it is ignored only in the `rewritten` tier, so "payment amount" still reaches
`amount_usd`, but an exact token match ranks 0.06 above the match with the extra token (G2).

#### 2.2 Phrase rules (every rule for approval)
A phrase rule produces an **extra** token form of the text. Both forms are matched, and a
candidate keeps the better one, so a rule can add a match but never remove one. Any match that
goes through a rule is `rewritten` (0.87). Each rule needs ≥ 3 linker cases that are not taken
from dev.jsonl (owner, Q2), and its effect is reported on linker-test separately from dev.

| id | pattern (on normalised text) | extra form | example (not from dev) |
|---|---|---|---|
| P1 | `number of X` | `X count` | "number of sessions" → `session_count` |
| P2 | `how many X` | `X count` | "how many sessions per day" → `int_sessions_daily.session_count` |
| P3 | `count of X` | `X count` | "count of sessions per channel" → `session_count` |
| P4 | `total X` | `X total` | "total shipping cost" → `shipping_cost_total` |

`X` is the rest of the phrase up to a stopword boundary (`per`, `by`, `for`, `on`, `in`, `of`,
`from`, end of text). Plural stripping applies to `X`, so "orders" becomes `order`.

Note on P3: "count of X" is the only rule whose extra form is also reachable by word order, but
only after `of` is dropped as a stopword. It stays as an explicit rule so that its effect is
measured. The P3 cases will be drawn from `*_count` columns (`session_count`, `order_count` in
`fct_daily_revenue`, `segment_order_count`), and the generator rejects a case whose gold is not a
`*_count` column.

Rules considered and rejected: `number → count` as a plain token rewrite, because "order number"
is not a count; `average X → X average`, because word order already covers it; `share of X`,
because there is no corpus use.

#### 2.3 Stopwords (text side only)
`the a an of per by for on in from at to with each all what which is are does do how where
when why column field`. A stopword is dropped only if it matches no token of the candidate's
column name, so names that contain one (`valid_from`, `orders_on_hand`-style) still match.
Phrase rules run **before** stopwords are dropped, because they need `of` and `how many`.

### Stage 3: hybrid over column cards
It runs only when stage 2's best candidate is **below the confidence bar B = 0.87**, meaning
there is no `surface` or `rewritten` match, and only when an index is available (§5).
- Query: the raw text. kinds = `["column"]`, k = 10, using the existing
  `SearchIndex.search(mode="hybrid")` (RRF, k = 60, depth 100). Hits are mapped to column ids
  through `chunk.column`. Hits that are not in the graph are dropped.
- **Eligibility (absolute, not rank-based):** a hit becomes a candidate only if its dense cosine
  similarity to the query is ≥ `COS_MIN` (§4.3). RRF ranks are relative: rank 1 always exists,
  even for junk, so a rank alone can never say "this matches".
- Score: `0.50 + 0.30 · rrf_norm`, where `rrf_norm = rrf / (2/61)` (1.0 means rank 1 in both
  lists). The range is (0.50, 0.80]. Its top equals the fuzzy bound on purpose: neither stage-3
  evidence nor stage-2 fuzzy evidence can outrank a `rewritten` match.

**Ranking when stage 3 runs (owner amendment):** the below-bar stage-2 candidates (fuzzy) and
the stage-3 candidates are ranked **together on score**. A column found by both keeps the
higher score and that stage's `match` label. A planned unit test: a below-bar stage-2 candidate
(fuzzy 0.55) loses to a strong stage-3 candidate (0.78).

## 3. Scorer

### 3.1 Features and weights (set by reasoning, not fitted)
| feature | applies to | value | reasoning |
|---|---|---|---|
| stage / tier base | all | 1.00 / 0.97 / 0.93 / 0.87 / ≤0.80 / (0.50, 0.80] | Tier gaps are ≥ δ (0.05) except exact_id vs exact_name (0.03, both stage 1) and fuzzy vs hybrid (they share a range and are ranked together). So a stronger tier is never "ambiguous" against a weaker one, while two candidates in one tier can be. 0.93 and 0.97 are v1's values, kept so that unchanged v1 behaviour keeps unchanged scores. |
| name similarity (fuzzy) | stage 2 fuzzy | `0.80 · (0.7 · overlap + 0.3 · seq)` | `overlap` = soft Dice over tokens with **each column token used at most once** (the fix for >1.0: greedy one-to-one matching, tokens ≥ 0.8 difflib ratio). `seq` = difflib ratio of the joined strings. 0.7/0.3 is v1's split: token agreement matters more than character shape, but typos ("revnue") need character shape. Bounded in [0, 0.80]. |
| model named in the text | stage 2, 3 (not stage 1, not dotted text) | `+0.06 · coverage` | `coverage` = share of the model's name tokens (without layer prefixes `raw stg int fct dim`) found in the text ("per customer" → `dim_customers`: 1/1; `dim_customer_rfm`: 1/2). Those tokens are then removed from the column-matching side. Full coverage is the same evidence as a dotted id, so it must be able to break a tie: 0.06 > δ. Partial coverage gives 0.03, which orders candidates but does not disambiguate them. |
| layer preference | stage 2, 3 | marts +0.010, intermediate +0.005, staging 0, raw/seed −0.005 | Questions usually ask about consumer-facing columns, but the layer is weak evidence. The total spread is 0.015 < δ, so it **orders ties but never resolves ambiguity** on its own. dev-16's two `previous_order_date` columns stay ambiguous, and the chain policy still picks the downstream one. |
| hybrid rank | stage 3 | `0.30 · rrf_norm` | Above. |
| extra tokens | stage 2 | part of the tier | `rewritten` (weak tokens dropped) is 0.06 below `surface`, and fuzzy Dice penalises extra tokens through its denominator. |

Score cap for stages 2 and 3: **0.96**, so that no non-exact candidate reaches the 0.97 exact
name. Stage 1 is lexicographic anyway; the cap keeps the printed scores honest.

### 3.2 Worked examples (the targets)
| text | top-1 (score parts) | runner-up | ambiguous |
|---|---|---|---|
| `dim_customer_segments.customer_segment` | itself, exact_id 1.00 | (stage 2/3) | no |
| "lifetime value" | `dim_customers.lifetime_value` surface 0.93 + marts 0.01 = 0.94 | `fct_customer_leaderboard.lifetime_value_usd` rewritten 0.87 + 0.01 = 0.88 | no (gap 0.06) |
| "number of orders per customer" (dev-15) | `dim_customers.order_count` rewritten (P1) 0.87 + model 0.06 + marts 0.01 = 0.94 | `fct_daily_revenue.order_count` 0.87 + 0.01 = 0.88 | no (gap 0.06) |
| "prod category on order items" (dev-14) | `int_order_items_enriched.product_category` rewritten (prod) 0.87 + model (order, item: 2/3 of `order items enriched`) 0.04 + int 0.005 = 0.915 | other `product_category`/`category` columns ≤ 0.875 | no |
| "previous order date" (dev-16) | `fct_orders.previous_order_date` surface 0.93 + 0.01 = 0.94 | `int_customer_order_history.previous_order_date` 0.935 | **yes** (chain policy, unchanged) |
| "refund amount" (trap 8) | `refund_amount` columns, surface 0.93 (+layer) | `refund_amt` rewritten 0.87; `refunded_amount` fuzzy | between same-name refund_amount columns only |

These are hand calculations from the formulas. The unit tests assert them, and the report shows
the real numbers. The exact runner-ups depend on the corpus.

### 3.3 Why not fitted
There are 20 dev questions, of which only 3 are description-worded. Fitting to them would only
memorise them. The weights above come from a constraint argument (tier gaps against δ, the
prior spread below δ, the model bonus above δ). After S09 (96 dev) they are re-checked on dev
only, and any change is recorded with its before/after numbers in this doc's change log.

### 3.4 Tie-break (deterministic)
Score (rounded to 4 places), then column before model, then non-seed before seed (v1), then id.
`"revnue_finance"` → `fct_daily_revenue.revenue_finance` before `fct_orders.revenue_finance` by
id, as today (both are marts with the same fuzzy score). It is listed as **fragile** in
linker_gaps.yml, not as fixed.

## 4. No-match and ambiguity

### 4.1 No-match threshold τ = 0.60
A candidate below τ is not a candidate. If none remains, `candidates: []` with the existing note,
and the agent loop behaves exactly as it does today on empty candidates (owner, Q3). The
loop's unknown-column refusal for dotted ids is unchanged and still makes 0 LLM calls.

Reasoning. Under the bounded fuzzy formula:
- One of two tokens matching exactly (`ship date` vs `order_date`) gives overlap 0.5 and seq
  about 0.6, so 0.80 · 0.53 ≈ 0.42 < τ. Sharing one word out of two is not a match.
- Two of three tokens matching (`order ship date` vs `order_date`) gives overlap 0.8 and seq
  about 0.75, so 0.80 · 0.785 ≈ 0.63 ≥ τ. That is a plausible "did you mean".
- A one-character typo in a two-token name (`revnue_finance`) gives about 0.77 ≥ τ.
- Every stage-3 candidate is ≥ 0.50 by construction, so τ removes only the weakest RRF tail.
  The real gate for stage 3 is `COS_MIN`.

τ sits between the one-of-two case and the two-of-three case, which is the boundary argued for.
**Evidence (to be produced, not fitted):** the report shows the score distribution of the top
candidate for linker-dev no-match cases against linker-dev positive cases. If τ = 0.60
misclassifies more than 10% of linker-dev no-match cases, τ is changed **once**, on linker-dev
only, and the change is recorded. linker-test is never used for this.

### 4.2 Ambiguity margin δ = 0.05 (unchanged)
`ambiguous = len(candidates) > 1 and top1 − top2 < δ`, as in v1, and the loop's `_ambiguity`
(chain / per-candidate / clarification) is unchanged. δ stays 0.05 because the loop imports it,
the presets were recorded under it, and the tier design above is built around it. Same-tier
candidates with the same evidence are ambiguous. A stronger tier, or a fully named model, is
not.

The tie set the loop uses (`score ≥ top − δ`) is unchanged, so with v2 it contains only
same-tier, same-evidence candidates.

### 4.3 Dense cosine floor COS_MIN = 0.80 (stage 3 only)
bge-small-en-v1.5's cosine similarities are compressed into a high band. Unrelated short texts
commonly score 0.6–0.75, and paraphrases usually score above 0.8. **This is the starting value,
and it is the one number in this design that rests on model behaviour rather than on the
formulas.** Evidence (to be produced): the report prints the cosine of the gold card against the
cosine of the best wrong card for linker-dev description-worded and no-match cases. The same
rule as τ applies: at most one recorded change, on linker-dev only.

### 4.4 False premises and non-existent columns
- dev-19 (`stg_orders.ship_date`): the loop refuses it before the tool phase (unchanged). If the
  linker is called with that text anyway, it returns no-match (§2, dotted rule).
- dev-17/18 (false premise with real ids): every id is exact, so stage 1 resolves it. The
  premise check is the validator's job (R8/R9) and does not change.

## 5. Install paths and output shape

- `Toolbox(graph, project_dir, index=None)`. With `index=None`, stage 3 is skipped and the
  payload carries `"hybrid": "unavailable"`. With an index, `"hybrid"` is absent when stage 3
  was not needed, and `"hybrid": "used"` when it ran. The core and demo installs never import
  `dlens.retrieval` (lazy import behind `index`; the unit test is an import guard).
  `demo/requirements.txt` and the demo-install job do not change.
- The index is used only if it is already built (`dlens search`, cached under `target/dlens/`).
  `resolve_entity` never builds it (owner, Q5). `dev_report.py` and `smoke_agent.py` get
  `--hybrid`. Every eval run manifest records hybrid on/off and, when it is on, the index key
  (`meta.json` `key`: model, revision, chunker version, chunks hash).
- **Payload (shown to the LLM), compatible with spec §7:**
  `{query, candidates: [{id, kind, match, score}], ambiguous, notes?, hybrid?}`.
  `match` ∈ `exact | normalised | fuzzy | hybrid`. `normalised` covers both the surface and the
  rewritten tier, so the existing values keep their meaning. `hybrid` is a new value, and
  `hybrid` is a new optional key.
- **Side record (not shown to the LLM; it goes to the run record and the UI):**
  `{scores: {id: score}}` as today, plus `parts: {id: {stage, tier, base, model_bonus, layer,
  rrf_norm?, bm25_rank?, dense_rank?, cosine?, rules: [P1, amt, word_order, …]}}` and
  `closest: [≤3 ids below τ]` when there is no match.
  **Decision for approval:** `closest` lives in the side record only. It is display-only (owner,
  Q3), and keeping it out of the payload means the LLM can't adopt a below-threshold id as an
  answer. The UI shows it under the empty result.
- Token cost: the payload adds at most `"hybrid": "unavailable"` (about 6 tokens) per call. The
  ~3K cap and context.py's compaction (which keeps `query`, candidate ids and `ambiguous`) are
  unaffected.
- **ADR 0022** records the additive payload key and match value, and the side-record fields.

## 6. Linker test set

Files under `eval/linker/` (new; not frozen; owner-reviewed before any number counts):
- `variants.yml`: **hand-drafted** mentions (synonym-style description wording, typos, phrase
  rule cases, no-match, model-qualified). Drafted from DESIGN_v2 tables and descriptions, the
  YAML descriptions and traps.yml. Never from parser output.
- `cases.jsonl`: generated by `scripts/gen_linker_cases.py` from `lineage_spec.yml` column names
  (mechanical variants) plus `variants.yml`. The generator asserts that every gold id is in
  lineage_spec.yml. It never loads the graph.
- `dev_mentions.jsonl`: the 20 dev targets with the mention each question uses (the id, or the
  phrase for dev-14/15/16). Reported separately and never in linker-test.
- `jira_sample.jsonl`: 20 dbt_jira mentions (public project) with hand-written gold, for the
  owner to check by hand.

Case schema: `{id, corpus, split, variant, mention, gold: [ids], expect_ambiguous, rule?,
source, note?}`. `gold: []` means no-match. Top-1 is correct if top-1 ∈ gold. Top-3 is correct if
any of the top 3 is in gold. No-match is correct if `candidates == []`.

**Split (owner, Q4):** by gold column, a stable hash of the first gold id into about 40%
linker-dev and 60% linker-test. No-match cases hash their mention. Any case whose gold column is a
dev.jsonl target goes to linker-dev. Phrase-rule cases are spread so that every rule has ≥ 2
cases in linker-test.

| variant | how it is made | target count |
|---|---|---|
| exact id | sample of spec ids, 12 per layer (raw, stg, int, marts) | 48 |
| exact bare name | spec column names; gold = every column with that name | 20 |
| abbreviation | reverse table on spec names (`amount → amt`, `quantity → qty`, …), ≥ 2 per used entry | 30 |
| word order | spec names with tokens permuted (≥ 2 tokens) | 20 |
| phrase rule | hand-drafted, ≥ 3 per rule (P1–P4), none from dev.jsonl | 16 |
| description wording | hand-drafted from DESIGN_v2 / YAML descriptions | 40 |
| model-qualified | "X of/on/in model" and "X per <entity>" | 16 |
| near-duplicate trap | trap 8 sets (refund_*, shipping_cost*), revenue_finance/marketing, order_count homonyms | 18 |
| typo | one edit in a token | 10 |
| no-match | plausible but non-existent (bare and dotted), out of domain | 30 |
| linker_gaps.yml | all 4 items (3 exact ids + "lifetime value") | 4 |
| **total** | | **≈ 252** |

## 7. Metrics (report only; `scripts/linker_report.py` → `eval/reports/linker.md`)
Top-1, top-3, no-match accuracy (on gold `[]` cases) and ambiguity rate (share of positive cases
flagged ambiguous, and separately the share of `expect_ambiguous` cases flagged), each per
variant and per winning stage. The systems are **v1** (frozen copy, `eval/linker/v1.py`), **v2
without hybrid** and **v2 with hybrid**, run on linker-dev, linker-test, dev mentions and the
jira sample. Each phrase rule's effect is shown on linker-test separately. These are not
benchmark metrics: `eval/metrics.py` and metrics-design.md are not changed.

## 8. Regression gates
1. **Presets, old records against v2:** replay the 10 presets with the v2 toolbox (no hybrid,
   as in the demo). Every payload except resolve_entity's must be identical. resolve_entity's
   top-1 and `ambiguous` must be identical. The recorded final answers must re-validate.
2. **Re-record** the 6 presets that call resolve_entity (dev-01, 07, 10, 13, 14, 16), locally
   on Ollama. Each must re-validate with the same verdict and the same resolve_entity top-1;
   otherwise **STOP and show the owner**. Every diff is reported.
3. **Dev:** `make eval-smoke` on the cached local runs. A changed resolve_entity payload changes
   the prompt, so those questions miss the cache and run on local Ollama (free). The target is
   ≥ 18/20, and every changed row is reported with its reason. dev-15 is expected to move from
   clarification to an answer.
4. `test_top1_on_every_exact_column_id` passes with an empty `exact_id_top1` list, and the
   `fragile` entry for "lifetime value" is removed, because the gap is now 0.06.

## 9. Alternatives rejected
- **Fitting weights** (logistic regression over features): too little labelled data, and it
  would tune toward the linker set we report on.
- **Always running hybrid and fusing it with stage 2:** demo payloads would differ from dev
  payloads for identifier queries, and an exact-looking query would pay for an embedding.
- **A cross-encoder reranker:** a new model and dependency. The column cards are short, and
  the failures are lexical (G1, G2) or caused by missing card text (G3).
- **Adding a YAML description to `dim_customers.order_count`:** that is a corpus/gold change
  and needs a bundle rebuild. It would fix dev-15 for the wrong reason.
- **Letting the LLM pick among candidates:** against "code guarantees, the LLM narrates".

## Change log
- 17 Oct 2026: first draft (S08 step 1).
