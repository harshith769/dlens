# Explain: validator (`src/dlens/agent/validator.py`)

Written by Claude at the owner's request (spec Decision 17). The owner reviews and approves it
and must be able to explain every rule from this page.

## What it does
`validate(answer, ledger, question) -> ValidationResult` checks an answer against what the tools
actually returned for this question. `ledger` is the per-question `Toolbox`. Seven rules plus one
repair run in code; no LLM is involved. The input answer is never modified. Repairs go into a
copy (`cleaned_answer`), and the raw draft stays untouched in the run record for the
no-validator ablation.

```
R1 cites → R2 in_ledger (+R2r repair) → R3 on_disk → R4 known_nodes → R5 kind_consistency
        → R7 relevance → R6 prose_refs
```

Each failure is `ValidationFailure{claim_index | None, rule, item_id, message}`. `claim_index`
None means the `answer_text` itself failed. The result carries:
- `passed`, `failures`, `cleaned_answer`;
- `repairs` (`{claim_index, from, to}`), `dropped_claims` (claims with ≥1 failure);
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

Claims that name no entity are exempt.

- **Why:** citation laundering. A real, in-ledger, on-disk id attached to an unrelated claim
  passes R2 and R3. R7 is also what makes the R2r repair safe (see above).
- **Catches:** "fct.total comes from stg.amount" citing the edge `raw.id → stg.x_id`; a repaired
  id that lands on such an edge.
- **False-positive risk:** a claim naming only a downstream consumer while citing an upstream
  edge two hops away fails. Exempt claims ("the value is renamed") are still covered by R2, R3
  and R5.

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

## Never used: `confidence`
`confidence` is the model's self-report. It is not evidence, it is not calibrated, and a model
that is confidently wrong is exactly the case the validator exists for. Using it would let the
model's own opinion of itself decide whether its claims are checked. It is shown and logged, and
used by nothing else.

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
