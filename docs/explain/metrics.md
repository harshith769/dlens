# Explain: benchmark metrics (`eval/metrics.py`, S10, v0.3 D3)

Implements `docs/plans/metrics-design.md` v1.1 (every definition is the owner's decision there;
M1–M16 below point at its sections). `metrics.py` `__version__` 1.1.0. Every scored report names
both versions.

## What it does

Takes the run records of one system and view (S0; S4 raw / validated / augmented; S1, which has
only its validated view), joins them to `eval/questions/dev.jsonl`, and scores each question against its gold:
node-set F1 in the question's primary mode, yes/no verdicts, refusals, clarifications,
false-premise rejection, path node coverage, hallucinated nodes and citation validity. Then it
aggregates (macro means, bootstrap CIs, breakdowns) and writes JSON + Markdown.

```
records.jsonl ─► adapter (adapter_for: from_record / from_s1_record) ─► Prediction ─► score_question ─► rows
     + manifest                                                       │
dev.jsonl ── join on exact text (fails on unmatched / duplicate) ─────┘
lineage_spec.yml + traps.yml ─► Inventory (columns, models, seeds, exposures, CTE names)
rows ─► summarise (macro means, bootstrap CI, breakdowns) ─► report .json / .md
```

## How it works

- **Imports.** `dlens.gold_spec`, the standard library and PyYAML (to parse `lineage_spec.yml`
  and `traps.yml`; `gold_spec` reads no files on purpose). Nothing from `dlens.lineage`,
  `dlens.agent`, `dlens.retrieval` or `dlens.graph`, so the system under test never grades
  itself. A run record is read as plain JSON, not through `RunRecord`.
- **Inventory (M8).** The 391 gold columns, 49 models, 14 seeds and 2 exposures, plus a list of
  CTE names and derived-table aliases found by plain regexes over the corpus SQL
  (`relation_names`): `<name> as (` for CTEs; `) as <name>` for a derived table only when
  `<name>.` is also used as a qualifier in the file. That second test is what keeps a column
  alias such as `cast(x as int) as amount` out.
- **Extraction (M2, M3).** `extract` turns prose into mentions:
  1. strip quotes, rewrite "Interpreted A as B." to "B.", remove file paths whole, protect
     `e.g.` / `i.e.` / `etc.` / `vs.`;
  2. dotted tokens pass the identifier filter (`classify`): an inventory column → `column`; a CTE
     name → `cte` (its own diagnostic); a known model/seed or a dbt-style model part →
     `unknown` (a hallucination candidate); anything else is plain text (`github.com`, `v0.3`);
  3. bare model names and exposure names (also with spaces) are mentions too; bare column names
     never are;
  4. the negation rule runs per sentence on a token list in which every mention is one
     placeholder token. `_clauses` gives each token a clause id (boundary words start a new
     clause; ", which / that / who … ," is its own clause). A mention is negated by a
     **pre** cue earlier in its clause or a **post** cue right after it. A cue followed by a
     value word ("null", "empty", …) before the next mention is void. A node mentioned once
     negated and once not is kept.
- **Mode (M4).** `primary_mode` returns the approved Appendix A mapping: trace family → direct,
  impact family → direct + indirect, Ask / unanswerable → none. `wording_cue` records the cue;
  the tests check it agrees with the family on every dev question except dev-50 (resolved by
  family, as Appendix A shows).
- **Scoring (M1, M5, M6, M9, M10, M12).** `score_question` computes every applicable metric in
  both modes (`row["modes"]`) and puts the primary one in `row["metrics"]`. Anything other than
  an answered prediction scores 0 on every set metric of an answerable question, even when the
  gold set is empty (`prf` gives ∅/∅ = 1 only to answered predictions). Yes/no reads only the
  structured `reach_verdict` through one accessor (`reach_verdict()`): the ADR 0024 `Answer`
  fields, else S0's record-level `structured.reach_verdict`. The raw view counts only the LLM's
  own value: the draft's, or a final verdict whose `reach_verdict_source` is `llm`. The
  first-sentence heuristic is a diagnostic. The false-premise bucket depends on whether the
  premise column is upstream of the target in the primary mode (`gs.reaches`): case U has
  rejected / not rejected, case O has rejected / asserted / silent.
- **Citations (M7).** `check_citation` re-reads the cited file itself (resolved path must stay
  inside the project): range in bounds, and the lines must hold the required column — the `to`
  column for a direct edge, the `from` column for an indirect edge, with the clause-key fallback
  (iv-k+) only when the key's relation is a CTE or derived-table alias of that file and the key
  is on the lines. `model` level is invalid (Jinja files without the column go to the macro
  bucket); `r_` facts are counted apart. An answered answer with no citation is invalid, unless
  its own `reach_verdict` is "no" (n/a, v1.1). Disagreements with the validator's R3 are
  counted from the record's `validation` failures, only for ids R3 ran on (`r3_checked`).
- **Statistics (M13, M15).** Bootstrap: 1,000 resamples with `random.Random(20261019)`,
  nearest-rank percentiles, shown only for n ≥ 10. Paired bootstrap on per-question differences
  and exact McNemar (`math.comb`) for S1 vs S4. Latency p50 / p95 from uncached runs only.
- **Composites (M16).** trace F1 = 44 questions, impact F1 = 24, node-set F1 = the 68 together.

## Why this design

- One extractor for every system, because S1 cites chunks, not edges: the S1-vs-S4 headline must
  not depend on a structure only one side has.
- A structured verdict only, because a regex over prose scores phrasing.
- Every gold set is read from dev.jsonl or computed by `dlens.gold_spec` from the spec. Nothing is
  read from the DLens graph, so S0's gaps measure the engine against the design, not against
  itself.
- Standard library statistics: no new dependency, deterministic, and they run in the core CI job.

## Alternatives rejected

- **Structured extraction (cited-edge endpoints) as the headline:** not available for S1. It
  stays a diagnostic (`structured_nodes`, `path_ordered_em`).
- **Parsing the validator's verdict or importing its R3 check:** that would grade S4 with S4.
- **numpy / scipy for the bootstrap and McNemar:** neither is in the core install. Twenty lines
  of standard library give the same numbers with a fixed seed.
- **Counting bare column names:** `order_date` exists in many models (owner M3 (i)).

## Implementation notes

- **Metric bug found by the identity test (fixed before any result was read):** dev-46 (clarify)
  carries a gold `paths` list. Path node coverage now skips clarify questions, whose correct
  answer is a clarification (design change log, 19 Oct 2026).
- **Reading of M8's denominator:** distinct filtered mentions in the answer, the question's own
  ids included (only the numerator exempts them).
- **S4-raw citations:** the draft has no attached citations, so the raw view uses the ledger's
  edge citations (`side_records.edges[*].citation`) and the final answer's map for anything else.

- **S1 records (metrics.py 1.2.0, S11).** `adapter_for(system)` picks `from_s1_record` for any
  system label starting with `s1`. It delegates to `from_record` (same RunRecord format) and
  enforces S1's invariants: S1 has only the validated view (no validator, so no raw or augmented;
  the CLI exits 2 on another view), and it never cites an `e_` edge (it can't see the graph). Its
  `c_` chunk citations come from `final_answer.citations`, attached by S1's code from the shown
  chunks. An id S1 cited but never saw stays uncited, and M7 scores it invalid. No scorer or
  definition changed: metrics-design stays v1.1. The S10 guess of a nested `{value, set_by}`
  verdict was replaced by the ADR 0024 shape; no committed record used it. A regression test
  re-scores the committed S0 records to the committed reports byte for byte (version stamps aside).

## Explain-back questions
1. "There is no direct edge from A to B." negates both A and B, and "A is not null and feeds B."
   negates neither. Walk through the clause ids, the cues and the value-word check that give
   each result. Which rule would have to change to keep B in the first sentence?
2. A refusal on dev-70 scores 0 on `columns_f1_direct`, but an answered "nothing is downstream"
   scores 1 on the same field. Why does M12 treat the two differently, and why does the headline
   still give the answered one 0?
3. Why must a derived-table alias appear as `<name>.` somewhere in the file before a clause key
   on it is accepted? Give the SQL line that would wrongly pass without that test, and say what
   citation-validity number it would inflate.
4. Someone runs `metrics.py --system s1-qwen3-4b --view raw`. What happens and why? An S1 answer
   cites `c_1a2b3c4d`, a chunk that was retrieved but did not fit the budget: what does M7 say
   about it, and which part of the pipeline decided that?
