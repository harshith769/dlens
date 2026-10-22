# Explain: validator (`src/dlens/agent/validator.py`)

Written by Claude at the owner's request (spec Decision 17). The owner reviews and approves it
and must be able to explain every rule from this page.

## What it does
`validate(answer, ledger, question) -> ValidationResult` checks an answer against what the tools
actually returned for this question. `ledger` is the per-question `Toolbox`. Nine rules, one
repair (R2r) and one completion step (R8c) run in code; no LLM is involved. The input answer is
never modified. Repairs and completions go into a copy (`cleaned_answer`), and the raw draft
stays untouched in the run record for the no-validator ablation.

```
R2 in_ledger (+R2r repair) → R8c completion → R1 cites → R3 on_disk → R4 known_nodes
        → R5 kind_consistency → R7 relevance → R8 connectivity → R9 verdict → R6 prose_refs
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
  deletion), **or** the bad id is a prefix of it with **≥5 hex characters** (`MIN_PREFIX_HEX`;
  7 until S13b).

The candidate set is the union of both tests, and 0 or ≥2 candidates means no repair. Seen
live: `e_4b2_403a` (one wrong character) and `s_b3ece5f` (last character dropped).

**Changed in S13b (F4, post-pilot-fixes.md): 7 → 5 hex.**
- *Why.* On dev-16 (qwen pilot) the only claim naming the question's target cited `e_81a3f`,
  cut to 5 hex. It failed R2, the regenerate's rewrite failed R5, and salvage kept no claim
  about the target (chain 1.0 → 0.5). With 5 hex there is exactly one emitted match,
  `e_81a3f693`, and the repaired claim passes every rule.
- *The value* was fixed before looking: 5, as written in the design, with no other value tried.
  Step 0 found one 5-hex repair across both pilot models, no ambiguous one, and none landing on
  an id outside the gold set.
- *The guard that stays.* The repair needs **exactly one** same-prefix candidate. Two emitted
  ids sharing the 5 hex characters, a 4-hex prefix, or an `s_` stub for an `e_` id are not
  repaired. A 5-hex prefix leaves 16⁵ ≈ 1M possibilities against a ledger of tens to hundreds
  of ids, and a repaired id still goes through R3, R5 and R7, so a wrong pick is still caught
  (safety argument below).

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
- level `line`: the range contains the column name (word boundary, case-insensitive). **Which
  column depends on the edge's kind** (S12a, A5): a direct edge needs its `to` column; an
  indirect edge (record `indirect: true`) its `from` column, or else its clause key `rel.col`
  with `rel` a CTE or derived alias used as a qualifier in the file and `col` on the lines. This
  is metrics M7 (iv) exactly: without it R3 would drop almost every indirect citation metrics
  accepts (598 of 621 name the from column, 0 the to column). A shared fixture
  (`tests/fixtures/citations/indirect_cases.json`) is checked by an R3 test and by an M7 test,
  neither importing the other;
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
  hallucinations slip through.

**SQL alias tokens (changed in S13b, F2, option (a)).**
- *What.* `alias.column`, where `alias` is a relation alias in the source file of a model in
  this question's evidence, is **not a node name**. It is neither hallucinated nor supported,
  so R4 skips it. The aliases are `{{ ref(...) }}` / `{{ source(...) }}` aliases (with or
  without `as`), CTE names and derived-table names (`provenance.alias_names`).
- *How the names are found.* Alias tokens come from a regex over the source file, used only to
  mark a token "not a node name". No edge is built from them, and they are not a lineage parse.
- *Why.* The model sometimes writes the SQL alias instead of the model name:
  `DATE_TRUNC('MONTH', orders.order_date)` for `{{ ref('fct_orders') }} as orders`. Metrics M3
  never counted such a token as a mention, while R4 called it hallucinated. On dev-46 that
  turned a correct answer into "no verifiable claims" (a false refusal). Now the validator and
  the metric read the same token the same way (rule 12).
- *Why skip, not rewrite.* `orders` names three different models across dev-46's files.
- *Guards that stay.*
  - An alias that is also a real model name is checked as that model.
  - An unknown `foo.bar` (not an alias of an evidence model, not a node) still fails
    `R4.hallucinated`.
  - So does a real model's unknown column (`fct_orders.net_paid_us`).
  - R7 and R8 never counted alias tokens (they are not in-graph entities).
- *The cost, stated.* Two dev claims the prep audit classed as gold-inconsistent now pass:
  dev-44 #1 (`rfm_scores.*`, a CTE) and dev-45 #0 (`margins_monthly.*`, a derived table). Both
  are inconsistent only because of the alias token itself, and their real nodes are in the gold
  set. Both are pinned as tests.

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

1. **Only ledger edges, direct only.** The path is built from DIRECT edges this question's tools
   emitted, never from the whole graph. The tools still have to have found the evidence. Since
   S12a indirect edges are in the ledger too, but they never bridge: completion adds value
   derivations, and a path through a join key would assert one that does not exist. (A claim
   may still cite an indirect edge itself; R8 counts it as a link.)
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

### `r_` reachability facts in R2, R3, R7 and R8
For a yes/no question naming exactly two exact columns with reachability wording, code adds one
fact id `r_<8 hex>` to the ledger (agent.md, "Reachability fact"). Its record holds `from`, `to`,
`reaches`, `hops`, `reverse_hops`, the shortest-path edge ids and the sentence, e.g.
`raw_payments.amt does NOT reach dim_customers.lifetime_value (graph check)`. It has no file
citation, and `render()` marks it `[graph check]`.
- **R2/R2r:** `r_` is a third id prefix, so it is accepted when emitted, repaired under the same
  rule (same prefix, so never into an `e_`/`s_`), and checked in prose.
- **R3:** re-runs the reachability check on the graph and compares `reaches`, both hop counts and
  the path. A forged or stale fact record fails.
- **R7:** an `r_` id touches both of its columns (and their models), like an edge.
- **R8:** a cited `r_` connects its two columns, *whatever it says*. "raw.id does not reach
  fct.total" citing the fact names two unconnected columns, and the fact is exactly the evidence
  for that claim. It connects only those two: a third named column still needs an edge.
- **R8c:** an `r_` fact is never the *anchor* for completion (a "does NOT reach" fact must not
  license bridges to other columns); only cited edges anchor.

### R9 `rule_verdict`: the yes/no verdict matches the graph check
Runs only when an `r_` fact exists. Since S12a (ADR 0026, R9 option (a)) the fact's verdict uses
direct + indirect hops (yes/no is impact family, metrics M4), and its text states the direct
reading too: "X reaches Y in 1 hop (graph check: with indirect dependencies; not through direct
edges)". R3 re-runs the same two-mode check (`direct_reaches` / `direct_hops` included). R5 is
unchanged: no indirect kind is in a `KIND_WORDS` row, so "aggregated" over a JOIN edge fails.
- `answer_text`: the verdict of its **first sentence** must equal the fact (`reaches` → yes).
  No verdict is a failure (`claim_index` None).
- a claim that **cites** the `r_` id must not state the opposite verdict (a claim with no verdict
  is fine; it may just describe a path).
- **the structured field** (S12a, s12-design A2 option (b)): `Answer.reach_verdict` (copied from
  the draft by `attach`, source `llm`) fails when it is set and disagrees with the fact, or when it
  is null while the first sentence states a verdict. Null with no prose verdict adds no second
  failure (the prose check already failed it), and the field is never checked when there is no
  `r_` fact, so an impact or trace answer that sets or leaves it is not failed by R9.

**R9 reads only the system's own signals:** the `r_` fact (made by code from the question's
exact ids and wording, `loop._reachability_fact`) and the answer. It never reads a question
family, a gold label or anything under `eval/`; `tests/unit/agent/test_eval_boundary.py` checks
that `src/dlens/agent` imports nothing from `eval/` and names no `eval/` path or question file.
Metrics reads the field only on yes/no questions (M5).

**Verdict heuristic** (`answer_verdict`), on the first sentence (split at `.`/`!`/`?` followed by
whitespace, so `model.column` does not split it):
1. a leading "Yes" → yes; a leading "No" → no;
2. otherwise any negation (`not`, `n't`, `never`, `cannot`, `no`, `none`, `neither`) → no;
3. otherwise a reach verb (affect, impact, depend, feed, flow, reach, change, propagate,
   influence) → yes;
4. otherwise no verdict.

- **Why:** dev-10. The model answered "Yes, amt affects lifetime_value" and the answer passed:
  the false link was in `answer_text`, its one claim named a single column, so neither R7 nor R8
  could see it. Reachability is a fact code can compute exactly, so code computes it and the
  model's verdict is held to it.
- **Catches:** "Yes" when the graph says not reached; "No" when it is reached; an answer that
  never says yes or no; a claim citing the fact with the wrong verdict.
- **False-positive risk:** "X does not *directly* affect Y; it flows through Z" reads as "no"
  (negation before the reach verb) and fails when the fact says reached. The regenerate hint
  states the fact, so the model usually rewrites it as "Yes, through Z". A claim citing the fact
  that describes the *reverse* direction ("Y reaches X") reads as "yes".
- **Flow:** on an R9 failure the regenerate prompt gets the line `The graph check says: r_…:
  <fact>` first (clipped to 240 chars, never cut). The failure lines that follow are bounded by
  the room left under the cap (A6, see agent.md "Failure handling"). If the second draft still fails, salvage leads the rebuilt
  answer with **code's verdict claim** (`No: <fact>`, citing `r_`) and sets `validation_warning`.
  This verdict claim is kept even if every LLM claim failed, so the answer is not refused.
  Whenever salvage runs after an R9 failure it also sets `reach_verdict` to the fact's verdict
  with `reach_verdict_source = "code"`. Without an R9 failure the model's field is kept (`llm`).
- **Calls:** an R9-triggered regenerate is the existing "regenerate once" call (phase
  `regenerate`, inside the 8-call cap). The raw view never sees it: `record.draft` is set once
  from the first answer draft, the regenerate is logged only in `regenerate_draft_raw`, and
  metrics' raw view reads `draft` (metrics-design M3 rule 5; pinned by
  `test_flow.py::test_raw_view_reads_the_first_draft_never_the_regenerate`).

**Why not R8 on `answer_text` instead?** It would reject correct answers. A correct "No,
raw_payments.amt does not affect dim_customers.lifetime_value" names two columns that are *not*
connected; that is the point of the sentence. A connectivity check cannot tell a true negative
from a false positive without parsing negation in free prose, and parsing it is exactly the
fragile part. R9 needs to parse only one yes/no verdict, and compares it to a fact computed on
the whole graph (not only on what the tools happened to emit).

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
   identifier per line, at most ~300 tokens; on R9, the graph-check fact first). The new draft
   is validated.
3. If the regenerated draft passes, it is the answer (`regenerated: true`).
4. If both drafts fail, or no call is left, **salvage**: take the round with more passing claims
   (ties go to the regenerated one) and keep only its passing claims. **Rebuild `answer_text`
   from the kept claims' texts** whenever a claim was dropped, or the text itself failed (R2,
   R4, R6 or R9). In live run g, a salvaged answer's prose still stated the lifetime_value link
   that R8 had just removed from the claims. With an `r_` fact, a rebuilt text starts with code's
   verdict claim. Set `validation_warning`. If no claim passes (and there is no fact), refuse
   ("no verifiable claims").
5. Invalid JSON on the regenerate counts as a failure, and the first draft is salvaged.

**Live coverage.** `scripts/smoke_agent.py --inject-bad-draft KIND` swaps the first draft for a
bad one and lets the real model regenerate, so steps 2–3 run live. Salvage (step 4) is covered
only by scripted tests, on purpose: it makes no LLM call, so a live run would execute exactly the
same code on the same inputs.

The run record keeps the untouched first draft (`draft_raw`, `draft`), the regenerated draft
(`regenerate_draft_raw`) and both validation rounds (`validation.first`, `validation.second`)
with failures, repairs and per-rule counts. That is everything the no-validator ablation and the
raw-vs-repaired benchmark split need.

## `c_` chunk ids (S12b, B4): R2, R3 and R4
- **R2 / R2r:** `c_` is an id prefix like `e_`, `s_`, `r_`, so a cited chunk id must have been
  shown in this question, and a one-character miscopy of a shown one is repaired.
- **R3 (named in s12-design B4):** a chunk citation is checked by the rule S1's ledger citations
  follow: the file exists and the range is in bounds; at `star` level the lines contain `*`; at
  `line` level they name the chunk's entity (its column for a column card, its model for a model
  description cited from `- name:`); a model's SQL chunk must cite that model's own file; other
  docs (exposures, README) have no entity to check. All 506 fixture chunks pass.
- **R4 (owner decision, 21 Oct 2026, found from code before any run):** the evidence R4 accepts
  also takes each **shown** hit's **own** entity: the column / model in its side record, only if
  it resolves in the graph. A name that only appears in the hit's text never counts. Without
  this, a claim naming the column a hit is about would fail `R4.unsupported` whenever no lineage
  tool returned that column, so G4 would do nothing in the validated view.
- **c_ supports existence and description, never an edge.** A chunk is not a link: R8 counts only
  `e_` / `r_` ids as links, so a claim joining two columns ("A is derived from B") that cites
  only chunks fails R8, exactly as one citing only `s_` excerpts does today (test). R5 checks
  kind words only against cited edges, so it does not fire on a chunk-only claim. A one-column
  claim with a lineage word ("A is derived from raw data", `c_` only) names no second column, so
  no rule catches it; that is the same gap as for `s_` excerpts (known limitation).

## Claim labels (S12b B3, ADR 0025): `origin`, set where the validator already acts
The validator labels claims but never decides anything from a label. R2r sets `repaired` on a
claim whose cited id or prose id it rewrote; R8c sets `completed` on a claim it added edges to
(after R2r, so `completed` wins); `verdict_claim` (salvage) is `verdict`. The rule outcomes are
pinned: `tests/unit/agent/validator/conftest.py` digests every `validate` / `salvage` call of the
validator tests (failures, repairs, completions, dropped claims, counts, cleaned and salvaged
answers) with the S12b labels stripped and compares them with a snapshot recorded on the pre-B3
code (`tests/fixtures/validator/outcomes_pre_b3.json`: 106 tests, 81 calls; hypothesis tests
excluded because their draws vary). Not stripping `origin` makes 50 of them fail, so the check
is live. `premise_corrected` is never read or written by the validator.

## Never used: `confidence`
`confidence` is the model's self-report. It is not evidence, it is not calibrated, and a model
that is confidently wrong is exactly the case the validator exists for. Using it would let the
model's own opinion of itself decide whether its claims are checked. It is shown and logged, and
used by nothing else.

## Known limitations
- **`answer_text` gets fewer checks than claims.** It is checked by R2 (ids in prose), R4 (known
  nodes), R6 (paths and lines) and, for yes/no reachability questions, R9 (the verdict) only. R1, R3, R5, R7 and R8 apply to claims, because claims
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
S12a (A5):
- D. A claim cites only a JOIN edge stg.x_id -> fct.total and says "fct.total is aggregated from
  stg.x_id". Which rules fail it and why? Would R8c have bridged raw.id to fct.total through that
  JOIN edge?
- E. The fact for dev-74 says "reaches … not through direct edges". What verdict must the answer
  give, and which metric mode makes that the right answer?

S12a (A2):
- A. The fact says raw.id does NOT reach fct.total. The draft's prose says "No, …" but its
  `reach_verdict` is "yes". Which R9 failures fire, what does the regenerate prompt start with, and
  if the second draft is also wrong, what do `reach_verdict` and `reach_verdict_source` hold?
- B. An impact question names two columns with "affect" wording, so a fact exists, but the model
  answers with a column list and leaves the field null. When does R9 fail it, and when not? Why
  doesn't R9 decide "is this a yes/no question" from the question's family?
- C. After an R9 regenerate, which draft does metrics' S4-raw view score, and where in the
  record is the regenerated draft?

Earlier:
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
8. dev-10's wrong "Yes" passed R1–R8. Walk through what happens now: which code step makes the
   `r_` fact, what R9 reads, what the regenerate prompt says, and what the user sees if the
   second draft also says "Yes".
9. Why is "R8 on `answer_text`" the wrong fix for dev-10? Give the correct answer it would
   reject, and say why R8 lets a claim citing a "does NOT reach" fact connect its two columns.
10. "Does raw.id affect fct.total or fct_star.total?" names three columns. Why does code make no
   fact, and what still checks that answer? What would go wrong with a fact for only the first
   two?
11. (S12b, B3) The outcome snapshot strips `origin` before hashing. What would a validator change
    have to look like to pass every rule test but fail the snapshot, and why exclude the
    hypothesis tests from it?
12. (S12b, B3) Salvage leads with code's verdict claim. Which `origin` does it carry, which
    metrics view counts it, and why would `augmented` be wrong?
13. (S12b, B3) R2r rewrites an `e_` id written in a claim's prose but leaves the cited ids alone.
    Is the claim `repaired`? Point to the line that decides it.
14. (S12b, B4) A search_docs hit about `stg_payments.amount_usd` quotes text naming
    `fct_orders.revenue_finance`. Which of the two columns may an answer name with only that
    hit's `c_` id, and which rule decides?
15. (S12b, B4) Why does "int_payment_events.event_amount_usd is derived from
    stg_payments.amount_usd" citing two `c_` ids fail, and which rule fails it? What would make it
    pass?
16. (S12b, B4) A model's SQL chunk is cited at `line` level but its lines never name the model.
    What does R3 check instead, and why?

S13b (F4, changed in S13b):
17. dev-16 cites `e_81a3f`. Walk through R2r with 7 hex and with 5 hex. Which later rules check
    the repaired claim, and what would they catch if the repair had picked a wrong edge?
18. A ledger holds `e_81a3f693` and `e_81a3f0aa`, and a claim cites `e_81a3f`. What does R2r do
    and why? What about `e_81a3`?
19. Why was the value 5 fixed before the diagnosis ran, and why does a dev-16-style fix still
    need the test set after the 7 Dec freeze as its honest check?

S13b (F2, changed in S13b):
20. dev-46's claim says "derived from fct_orders.order_date using DATE_TRUNC('MONTH',
    orders.order_date)". Walk through R4 before and after F2. Why would rewriting `orders` to a
    model name be unsafe, while skipping it is not?
21. A claim mentions `stg.nope_col`, and `stg` is both a model and an alias in another model's
    SQL. What does R4 say, and why?
22. Alias names come from a regex over the source file, not from the lineage engine. What may
    they be used for, what may they never be used for, and which metric rule do they mirror?
