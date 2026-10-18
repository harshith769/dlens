# Explain: the dev question generator (S09)

Files: `scripts/question_pools.py` → `eval/questions/pools.yml`; `scripts/gen_dev_questions.py` →
`eval/questions/review/dev_candidates.jsonl`. Hand inputs: `eval/questions/review/ask_drafts.yml`
(the 12 Ask questions) and `eval/questions/review/v02_dev.jsonl` (the frozen 20 v0.2 questions).
Design: `docs/plans/questions-design.md`.

## What it does
It builds the 96 dev questions of the benchmark (spec §11.2) in two stages.
1. **Pools.** Every spec column goes to dev or test before any question exists.
2. **Generator.** It picks dev-pool targets for each row of the count table, words each question
   from a fixed template, and computes its gold from `lineage_spec.yml`.

The output is a candidate file. Questions count only after the owner has decided on each one
(accept / fix / drop) and `scripts/apply_review.py` writes `eval/questions/dev.jsonl`.

## How it works
- **Pools.** A stratum is (hop bucket, rarest trap). Small traps (≤ 5 columns) form one stratum
  across buckets, so the two stale-doc columns split 1/1.
  - Inside a stratum, columns are ordered by `sha256("s09-pools-v1:" + id)`. About 30% go to dev.
  - The v0.2 targets, and the other columns their frozen texts name, are forced into dev.
  - A coverage check fails if the dev pool can't supply the count table. It never borrows a test
    column.
- **Slots.** `PLAN` lists (row, bucket, subtype, wording) slots. The 20 v0.2 questions are placed
  first. Each slot takes the first candidate in hash order, with two adjustments:
  - candidates that add an under-covered trap (< 2 questions) come first;
  - within a row, description slots are filled first, because they are the most constrained.

  Spares (identifier wording) replace dropped questions.
- **Gold.** Computed with `dlens.gold_spec` and nothing else:
  - trace: the input and upstream closures, both direct-only and direct + indirect;
  - impact: the downstream closures, plus the models and exposures they reach;
  - yes/no: reachability in both modes, plus a shortest path;
  - false premise: the premise edge, which holds in neither mode for generated questions;
  - ambiguous: every spec column with the same bare name;
  - unanswerable: refusal, plus the closest spec names (informational).

  Every direct edge in gold cites its line in `lineage_spec.yml`. The v0.2 questions keep id,
  text, target and `expect`. Their gold is recomputed from v2, and every difference is a review
  flag.
- **Wording.** There are four labels:
  - `identifier`: the template names `model.column`;
  - `name_words`: the column-name words, plus model words when the bare name is shared and the
    question is not about ambiguity;
  - `description`: the column's YAML description, used only if unique, ≥ 4 content words, not a
    stale-doc or injection text, and (for trace and computed questions) not naming an input;
  - `paraphrase`: the template is kept, and the local qwen paraphraser fills in the question.

  RFM-path impact and yes/no questions are worded as lineage ("downstream … in the lineage"),
  because `rfm_monetary_score` can never change `customer_segment`'s value.

## Why this design
- **Pools before questions.** Splitting by column (D5) first means the generator can't look at a
  test question, even by accident, and a test column can't leak through a dev question's target.
- **Gold from the spec only.** The parser and the linker are what the benchmark scores. If either
  wrote the answer key, the benchmark would grade itself.
- **Both direct and indirect sets in gold.** Which one is scored is a metrics decision (S10).
  Storing both now means no regeneration later.
- **Fixed templates plus a separate paraphrase step.** Template text is checkable by code. The
  paraphraser only rewords, and automatic flags send any drift to the owner.

## Alternatives rejected
- **Generating from the lineage graph.** It would be faster, but it breaks the CLAUDE.md gold
  rule and makes the benchmark circular.
- **Random sampling per row.** It isn't reproducible. The hash order is deterministic, so
  `--check` and the freshness test can pin the file.
- **Wording all impact questions as "what is affected".** On the RFM path the value never
  changes, so the gold set would be wrong in the value sense the wording implies.
- **Letting an LLM write the questions.** The model would see gold, and its wording would not be
  reproducible. Only the paraphrase step uses one, locally, on question text alone.

## Explain-back questions
1. Why do the two stale-doc columns end up in different splits, and what would have happened with
   (hop bucket, trap) strata alone?
2. dev-74 asks whether `int_product_costs_current.product_id` affects
   `int_order_item_margins.line_margin`. Its gold says direct "no", all "yes". Which spec rows make
   that true, and why is the question flagged `verdict_differs_by_mode`?
3. dev-17's text names `int_customer_order_history.sales_tax`, a column the first pool run put in
   test. What did S09 change so a frozen dev question never names a test-pool column, and which
   check enforces it?
