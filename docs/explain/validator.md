# Explain: validator (`src/dlens/agent/validator.py`)

Written by Claude at the owner's request (spec Decision 17). The owner reviews and approves it
and must be able to explain every rule from this page.

## What it does
`validate(answer, ledger, question) -> ValidationResult` checks an answer against what the tools
actually returned for this question. `ledger` is the per-question `Toolbox`. Eight rules, one
repair (R2r) and one completion step (R8c) run in code; no LLM is involved. The input answer is
never modified. Repairs and completions go into a copy (`cleaned_answer`), and the raw draft
stays untouched in the run record for the no-validator ablation.

```
R2 in_ledger (+R2r repair) → R8c completion → R1 cites → R3 on_disk → R4 known_nodes
        → R5 kind_consistency → R7 relevance → R8 connectivity → R6 prose_refs
```
(R8c runs before the rules, so every rule checks the completed claim.)

Each failure is `ValidationFailure{claim_index | None, rule, item_id, message}`. `claim_index`
None means the `answer_text` itself failed. The result carries:
- `passed`, `failures`, `cleaned_answer`;
- `repairs` (`{claim_index, from, to}`), `completions` (`{claim_index, added}`),
  `dropped_claims` (claims with ≥1 failure);
- `counts` per rule, and `regenerated`, `warning`, `skipped` (refused and clarification answers
  are not checked: they have no claims, and their text comes from code).

Rules build on one `ValidationContext` per call: the graph's model and column names, this
question's evidence (every column and model in its tool results, every SQL line a tool showed),
and files read **fresh** from disk.

## The rules

### R1 `rule_cites`: every claim cites at least one id
- **Why:** spec §8 rule 1. A claim with no id cannot be checked against anything.
- **Catches:** `{"text": "revenue_finance excludes tax", "ids": []}`.
- **False-positive risk:** none. An opinion-like claim without evidence should not be a claim.

### R2 `rule_in_ledger`: every cited id was emitted in this question
- **Why:** spec §8 rule 2. Ids from the model's memory, from another question, or invented are
  the commonest grounding failure of a small model.
- **Catches:** `e_deadbeef`; an id from the previous question (the ledger is reset per
  question); `s_6d4fdcfe` when only `e_6d4fdcfe` was emitted (wrong prefix).
- **Ids written in prose count too.** Every `e_`/`s_` token in `answer_text` or a claim's text
  must be in the ledger, under the same R2r repair rule. A repaired prose id is rewritten in
  `cleaned_answer` (repair recorded with `"in": "text"`). Live run g wrote ids inline, so prose
  can no longer carry an unchecked id.
- **False-positive risk:** a correct but miscopied id. R2r handles the safe subset.

### R2r `repair_id`: repairing a miscopied id
An id failing R2 is replaced only if **exactly one** emitted id qualifies:
- it has the **same prefix** (`e_` edge or `s_` excerpt), and
- it is within **Levenshtein distance 1** of the bad id (one substitution, insertion or
  deletion), **or** the bad id is a prefix of it with **≥7 hex characters**.

The candidate set is the union of both tests, and 0 or ≥2 candidates means no repair. Seen
live: `e_4b2_403a` (one wrong character) and `s_b3ece5f` (last character dropped).

**Safety argument:**
1. Ids are 8 hex characters of a sha1, so two emitted ids in one question are almost never one
   edit apart. If they are, there are ≥2 candidates and the repair is refused.
2. The prefix must match, so an edge can never turn into an excerpt or back.
3. A repaired id is not trusted: it still goes through R3 (the citation must hold on disk) and R7
   (the edge or excerpt must involve what the claim talks about). A repair cannot launder an
   unrelated id into a claim.
4. Repairs are recorded and reported separately in the benchmark (raw vs repaired), so they never
   hide a model error.

### R3 `rule_on_disk`: the citation still holds on disk
The citation comes from the ledger record (never from the answer, since the LLM never types
citations). The file is re-read fresh through `safe_read` (path-traversal safe). Checks:
- the file exists inside the project and `1 ≤ line_start ≤ line_end ≤ line count`;
- level `line`: the range contains the column name (word boundary, case-insensitive);
- level `star`: the range contains `*` (the column comes from `SELECT *`);
- level `model`: the file mentions the name (for a seed CSV, a header field);
- `s_` excerpt: the range exists and its text hash equals `text_sha1` recorded when
  `get_model_sql` ran.

- **Why:** spec §8 rule 3, "wrong lines must be rejected". It also catches files edited between
  the tool call and the answer, and a corrupted or hostile citation.
- **Catches:** a range past EOF; a range that lacks the column; `../secret.sql`; `as total`
  renamed to `as grand_total` after the tool ran.
- **False-positive risk:** a project edited during a run fails honestly. A column name that only
  appears through Jinja is cited at `model` or `star` level by the tools, so it is still checked
  correctly.

### R4 `rule_known_nodes`: no hallucinated or unsupported nodes in prose
Applied to `answer_text` and each claim text. It extracts:
- dotted identifiers (`model.column`, last two segments of longer ids). Paths and file
  extensions are skipped, and "e.g." is skipped because neither part is a model or contains `_`;
- bare words that are model, seed or source names **containing `_`** (dbt-style names, so plain
  English like `orders` or `customers` is not matched).

Verdicts:
- not in the graph → **`R4.hallucinated`**, always, even if the question contains it;
- in the graph but in none of this question's tool results → **`R4.unsupported`**, unless the
  question itself names it.

A dotted identifier that appears verbatim in a SQL excerpt a tool showed (e.g. a CTE column like
`order_agg.lifetime_value`) counts as evidence.

- **Why:** an answer can cite valid ids and still talk about a node no tool returned, or one that
  does not exist. False-premise questions ("why does fct_orders.discount_pct depend on
  stg_orders.amount?") must not let the model repeat the invented column.
- **Catches:** "fct_orders.discount_pct comes from…" (hallucinated); "…also feeds
  stg_payments.amount_usd" when no tool returned it (unsupported).
- **False-positive risk:** bare column names are not checked (too noisy), so some
  hallucinations slip through. A CTE alias written dotted but not shown in any excerpt is
  flagged as hallucinated.

### R5 `rule_kind_consistency`: kind words match the cited edges
It runs only when the claim cites ≥1 edge. For every word group that matches, at least one cited
edge must have an allowed kind. The table is `KIND_WORDS`:

| Words in the claim | Allowed edge kinds |
|---|---|
| `aggregat*` | AGGREGATION |
| `sum`, `summed`, `count(ed)`, `avg`, `average` | AGGREGATION, TRANSFORMATION |
| `renam*` | RENAME |
| `identity`, `unchanged`, `as-is`, `same value/column`, `passes through` | IDENTITY, RENAME |
| `transform*`, `computed`, `calculated` | TRANSFORMATION, AGGREGATION |

- **Why:** the edge kind is the parser's fact about how a column is derived. A claim that says
  "aggregated" while citing an IDENTITY edge contradicts its own evidence.
- **Catches:** "fct.x_id is aggregated from stg.x_id" citing the IDENTITY edge.
- **False-positive risk:** negation ("is not aggregated") still triggers. `sum/count/avg` allow
  TRANSFORMATION because "the sum of items_subtotal and sales_tax" is often plain `a + b`.
  Bare "same" is not in the table, because "in the same model" is ordinary English.

### R7 `rule_relevance`: cited ids touch what the claim names
For a claim that names ≥1 in-graph entity (R4's extractor), at least one cited id must touch one:
- an **edge** touches X if X is its from/to column, or X is the model of from/to;
- an **`s_` excerpt** touches X if its file is X's model file, or X's column name appears in the
  excerpt range.

Claims that name no entity are exempt. Ids that already failed R2 are ignored here (counted once,
under R2).

- **Why:** citation laundering. A real, in-ledger, on-disk id attached to an unrelated claim
  passes R2 and R3. R7 is also what makes the R2r repair safe (see above).
- **Catches:** "fct.total comes from stg.amount" citing the edge `raw.id → stg.x_id`; a repaired
  id that lands on such an edge.
- **False-positive risk:** a claim naming only a downstream consumer while citing an upstream
  edge two hops away fails. Exempt claims ("the value is renamed") are still covered by R2, R3
  and R5.

### R8 `rule_connectivity`: a multi-column claim is connected by its cited edges
For each claim naming ≥2 distinct in-graph columns (R4's extractor, dotted `model.column`), all
of them must lie in **one connected component** of the claim's cited edges, treated as
undirected over each edge's from/to.

Exemptions:
- claims naming fewer than 2 columns;
- `answer_text` (the claims carry the assertions);
- ids that already failed R2 (counted once, under R2).

- **Why:** R7 only asks that a cited id touch *one* named entity. In live run g a claim said
  "dim_customers.lifetime_value is aggregated from int_customer_order_history.items_subtotal"
  while citing only `fct_orders.items_subtotal → dim_customers.lifetime_value`. That skips a hop
  (the gold path goes through `fct_orders.items_subtotal`, lineage_spec l.120/142). R8 requires
  evidence for the whole relationship a claim asserts.
- **Catches:** the skipped-hop claim above; a false-premise "X comes directly from Y" citing one
  real edge that touches only X.
- **Passes:** the same claim citing the full chain; "X and Y both feed Z" citing X→Z and Y→Z
  (one component through Z).
- **False-positive risk:**
  - a claim naming two columns that cites only an `s_` SQL excerpt, which has no edges, fails
    (the model must cite the edge);
  - a claim that mentions an unrelated column in passing ("unlike stg_x.y, …") fails unless it
    cites a connecting edge.

### R8c `complete_citations`: completing an under-cited claim
R8 dropped claims whose prose was right but whose citations missed a connecting edge that the
tools *had* emitted. R8c adds those edges in code before the rules run, under four conditions:

1. **Only ledger edges.** The path is built from edges this question's tools emitted, never
   from the whole graph. The tools still have to have found the evidence.
2. **Anchor.** At least one of the claim's own cited edges must touch a column it names.
   Without this, completion would turn an unrelated citation into a relevant one: the added
   path touches the named columns, so R7 would pass. That would be laundering by code.
   Caught by the existing test `test_r7_a_repair_cannot_launder_an_unrelated_id`.
3. **Directed bridges between named columns.** Each bridge is a shortest *directed* lineage
   path, in either direction, ≤4 hops (`MAX_COMPLETION_HOPS`), from one named column to another
   named column in a different component. An undirected path is not enough: `quantity` and
   `unit_price` both feed `line_amount`, and an undirected path would "complete" the false
   "quantity comes from unit_price".
4. **"direct"/"directly"** (word boundary, so "indirectly" does not count) forbids any bridge
   longer than one hop. A multi-hop path cannot make a direct claim true, so the false-premise
   "X comes directly from Y" still fails R8. Negation is not parsed ("not directly" is also
   blocked), which errs on the strict side.

It is all or nothing per claim. Completed edges are then ordinary cited edges, so R3 (on disk),
R5 (kind words) and R7 (relevance) check them. For example, "fct_star.total is renamed from
stg.amount" citing the IDENTITY edge is completed with the AGGREGATION edge and still fails R5.
Completions are recorded like repairs (`completions`, in both validation rounds of the run
record). The benchmark reports first-draft claims as **raw** (passing with no repair and no
completion), **repaired** and **completed** (spec §8).

- **Catches (turns into a pass):** dev-03 "line_amount is quantity × unit_price" citing one of
  the two input edges; dev-09 "these 7 columns are affected by order_date" citing 6 edges.
- **Still fails:** a "directly" claim over a 2+ hop path; a claim whose only citation is
  unrelated; siblings; a column the tools never reached.
- **False-positive risk (a wrong claim passing):** the claim's *direction* is not parsed. "A
  comes from B" is completed by a path B → A or A → B. The kind words and R4 still apply, and the
  dev report scores the cited edges against gold.

### R6 `rule_prose_refs`: paths and line numbers in prose match a citation
It finds file paths (`*.sql|csv|yml|yaml`) and `line N` / `lines N-M` / `lines N to M`:
- a claim is checked against its own citations; `answer_text` against all of the answer's;
- a path must equal or end a citation's file;
- `line N` must lie in a non-`model` citation range, and `lines N-M` entirely inside one.

- **Why:** the model is told never to write files or lines, because code attaches them. When it
  does, the reference must be true.
- **Catches:** "defined at line 99"; "see models/other.sql" with no citation there.
- **False-positive risk:** "lines 3-4" spanning two separate one-line citations fails, and a
  line number about something other than a file (rare in lineage answers) is checked anyway.

## The flow in the loop (`loop.py: Agent._validate`)
1. Validate the first draft. If it passes (possibly with repairs), it is the answer.
2. Otherwise, if a call is left (`llm_calls < 8`, which the budget reserves), **regenerate once**:
   the same answer-phase prompt plus a short list of what failed (rule and failing id or
   identifier per line, at most ~300 tokens). The new draft is validated.
3. If the regenerated draft passes, it is the answer (`regenerated: true`).
4. If both drafts fail, or no call is left, **salvage**: take the round with more passing claims
   (ties go to the regenerated one) and keep only its passing claims. **Rebuild `answer_text`
   from the kept claims' texts** whenever a claim was dropped, or the text itself failed (R2,
   R4 or R6). In live run g, a salvaged answer's prose still stated the lifetime_value link that
   R8 had just removed from the claims. Set `validation_warning`. If no claim passes, refuse ("no
   verifiable claims").
5. Invalid JSON on the regenerate counts as a failure, and the first draft is salvaged.

**Live coverage.** `scripts/smoke_agent.py --inject-bad-draft KIND` swaps the first draft for a
bad one and lets the real model regenerate, so steps 2–3 run live. Salvage (step 4) is covered
only by scripted tests, on purpose: it makes no LLM call, so a live run would execute exactly the
same code on the same inputs.

The run record keeps the untouched first draft (`draft_raw`, `draft`), the regenerated draft
(`regenerate_draft_raw`) and both validation rounds (`validation.first`, `validation.second`)
with failures, repairs and per-rule counts. That is everything the no-validator ablation and the
raw-vs-repaired benchmark split need.

## Never used: `confidence`
`confidence` is the model's self-report. It is not evidence, it is not calibrated, and a model
that is confidently wrong is exactly the case the validator exists for. Using it would let the
model's own opinion of itself decide whether its claims are checked. It is shown and logged, and
used by nothing else.

## Known limitations
- **`answer_text` gets fewer checks than claims.** It is checked by R2 (ids in prose), R4 (known
  nodes) and R6 (paths and lines) only. R1, R3, R5, R7 and R8 apply to claims, because claims
  carry the assertions and their ids.
  - A passing answer's prose can therefore still summarise more than its claims prove.
  - The benchmark scores **claims**, not prose.
  - After salvage the prose is rebuilt from the kept claims, so it cannot outrun them.

## Resolved (session 5a): R8 strictness vs answer completeness
**Question.** R8 drops claims whose prose is right but whose citations miss one connecting edge.
Should code complete them?

**Decision rule, fixed before the run.** Count first-draft claims dropped by R8 whose named
columns are connected by this question's ledger edges ("completable"). Build completion if
completable drops are ≥ 10% of all first-draft claims; otherwise do not, and record the rate.

**Measured** (`scripts/dev_report.py`, 20 dev questions, qwen3:4b-instruct-2507-q4_K_M, 3 Oct 2026):
37 first-draft claims, 4 dropped by R8 (R8 was their only failure), all 4 completable:
**4/37 = 10.8% ≥ 10% → built.**
- Margin note: within 4 hops of the claim's *first* named column (the stricter pairwise
  measure), only 3/37 = 8.1% were completable, which would have been below the threshold. The
  fixed rule counts any connecting path, so the decision stands. R8c bridges from the nearest
  named column, so in practice all 4 completed within ≤4-hop bridges.
- Sample size: 4 events in 37 claims is small. Re-measure on the 96 dev questions in v0.3.

| first-draft claims | raw | repaired | completed | failed |
|---|---|---|---|---|
| before R8c | 28 | 5 | 0 | 4 |
| after R8c | 28 | 5 | 4 | 0 |

The 4 completed claims are dev-03, dev-08 and dev-09 (one edge added each) and dev-06 (4 edges
added, for a claim naming 4 columns along the deep chain). dev-03 went from fail to pass, mean gold-edge recall went from 0.62 to 0.72, and regenerate
calls fell from 4 to 0 (73 → 69 LLM calls). See docs/explain/eval-dev.md.

## Explain-back questions
1. `s_b3ece5f` is repaired to `s_b3ece5f8`, but a bad id `e_12345678` with two emitted ids
   `e_12345679` and `e_1234567a` is not. Walk through R2r for both. Which later rule would still
   catch a repair that picked the wrong edge, and why?
2. A question asks "why does fct_orders.discount_pct depend on stg_orders.amount?" and the
   answer restates the premise while citing a real edge. Which rule fails it, under which name,
   and why does the question's wording not exempt it?
3. R3 reads the file fresh instead of using the text the tool saw. What does that catch, and
   why are `s_` excerpts checked with a hash rather than a column name?
4. Give an answer that passes R2 and R3 but fails R7, and explain why R7 is needed for the
   repair rule to be safe.
5. R8c completes "fct_star.total comes from stg.amount" citing only the last hop, but not the
   same claim with "directly". Walk through both. Then explain why the anchor condition is
   needed: what would `fct.total comes from stg.amount` citing `raw.id → stg.x_id` do without it?
6. Why must R8c bridges be *directed* paths between *named* columns, when R8 itself checks an
   undirected component? Use quantity / unit_price / line_amount.
7. The completable rate was 10.8% by the fixed rule and 8.1% by a stricter 4-hop measure. Why
   is it important that the rule was written down before the run, and what would you check on
   the v0.3 dev set before keeping R8c?
