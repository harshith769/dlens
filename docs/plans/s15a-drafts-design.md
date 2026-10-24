# S15a design: test (224) and set-E (60) question drafts (v0.3 D5b)

**Status:** approved by the owner with the S15a plan (24 Oct 2026), including amendments A1–A4.
**Inputs:** spec §10, §11.1–11.2, §17; `questions-design.md` (D5a); `s13d-design.md` §2.5, §6;
`corpora/synthetic_shop/{DESIGN_v2.md, lineage_spec.yml, traps.yml}`; `corpora/dbt_jira/SOURCE.md`.
**Output:** `eval/questions/drafts/test_draft_v1.jsonl` (224) and `external_draft_v1.jsonl` (60).
They are drafts. The owner reviews them in Buffer A, and the owner alone writes `test.jsonl`,
`external.jsonl` and their `.sha256` files at the freeze (7 Dec 2026).

Rules that hold throughout:
- **Test gold** comes only from `lineage_spec.yml` through `dlens.gold_spec` (plus `traps.yml` and
  `pools.yml` for tags and the split). The test generator never imports the graph, the parser or
  the linker. Ask rubric facts come from corpus files, and each fact cites `file:line`. For the
  stale-doc trap, the facts follow the SQL.
- **Set-E gold** is the spec's documented exception (§11.1). It comes from the DLens graph of the
  pinned dbt_jira (complete closures), and every row says `gold_source: parser` and records the
  engine version and the graph hash. The owner audit (100–150 edges, 15–20 hand-traced columns)
  comes later.
- No system runs on any draft (S0–S4, the linker and the validator all stay off). Paraphrases come
  from local Ollama only.
- Scripts print ids, counts and check names. They never print question text, gold or facts.

## 1. Count tables (test, spec §11.2)

Trace (105), counted by the target's hop bucket. A false-premise question counts in its target's
bucket.

| Bucket | Total | upstream | computed | ambiguous | multi_part | false_premise |
|---|---|---|---|---|---|---|
| 1 | 21 | 16 | 2 | 0 | 1 | 2 |
| 2–3 | 28 | 14 | 7 | 2 | 2 | 3 |
| 4–5 | 28 | 17 | 5 | 2 | 2 | 2 |
| 6+ | 28 | 15 | 8 | 2 | 2 | 1 |

No test-pool column at 1 hop has an ambiguous bare name, so that cell is 0.

**Impact (70).**
- Downstream 56, bucketed by the source's longest direct downstream path: 1: 14 · 2–3: 14 · 4–5: 12 ·
  6+: 11 · indirect-only: 5. At least 3 have `focus: exposures`, and at least 1 of them reaches only
  one dashboard.
- Yes/no 14: 5 yes (direct) · 3 yes only with indirect edges · 6 no. The gold is the verdict.
- The RFM-path lineage wording follows D5a (questions-design §3).

**Interpreted near-miss (3, inside the rows above):** 1 trace upstream and 2 impact downstream. The
mention drops a unit suffix of a test-pool column, and the shortened id must not exist. These rows
carry `gold.interpretation: {text, column}` and the flag `interpretation`, and are scored under
metrics-design M9 v1.2.

**Ask (28), hand-drafted:**
- revenue definitions 6 · stale doc 2 · near-duplicate grain 5 · CASE meaning 6 · star exclusion 3 ·
  filter semantics 3 · rename / fan-in / join-key meaning 3;
- `doc_injection` has no test-pool column, so it gets no test question (reported).

**Unanswerable (21):** dotted near-miss 8 · bare 4 · typo in a dotted id 3 · unknown model 3 ·
out of domain 3. They are built mechanically from test-pool columns and from word lists kept in
`eval/questions/drafts/hand/`.

**Wording (224):** identifier 112 · name_words 42 · description 23 · paraphrase 47. As in D5a, a
description slot with no usable description falls back to name_words and is flagged.

**Traps:** all 9 traps appear, with at least 4 questions each, counted per question (questions-design
§1.2 amendment). A shortfall is reported, never filled from dev.

## 2. Set E (dbt_jira, 60)

- Trace 40: 10 per bucket (1, 2–3, 4–5, 6+), split 30 upstream and 10 computed.
- Impact 20: downstream 16 (buckets 5/5/3/3) plus yes/no 4.
- Wording: identifier 36 · name_words 10 · description 6 (jira YAML) · paraphrase 8.
- A bucket the graph cannot fill moves its gap to the next deeper bucket, then to the next shallower
  one, and the move is reported. dbt_jira has no `traps.yml`, so `traps: []`.
- Gold: `scripts/build_external_gold.py` builds the vendored project (dbt-duckdb, offline) and
  exports the graph into `eval/questions/drafts/external_gold_graph_v1.json`. The export holds
  short-id nodes, direct edges, indirect pairs, model dependencies and meta (versions, pin,
  `graph_sha256` = sha256 of the full graph JSON, `export_sha256`).
  `scripts/gen_external_drafts.py` loads the export as a `gold_spec.View` and reuses the D5a gold
  functions.

### 2.1 Set-E gold drift guard (A3)

**Before the freeze, rebuild dbt_jira with the frozen engine and compare its graph_sha256 with
external_gold_graph_v1.json meta; any mismatch → STOP (set-E gold must be regenerated and
re-reviewed).** The owner runs it at the freeze:

```
uv run python scripts/build_external_gold.py --verify    # rebuilds in a temp dir, writes nothing
```

This rule is also a row of the freeze checklist (`s13d-design.md` §6).

## 3. Draft schema

The draft rows carry the dev.jsonl fields plus:
- `draft_id` (`t1-NNN` or `e1-NN`, stable through review);
- `gold_source` (`spec` | `parser`) and `gold_meta` (set E: `dlens_version`, `sqlglot`, `dbt_core`,
  `dbt_duckdb`, `corpus_commit`, `graph_sha256`, `export_sha256`);
- `stratum` and `review_flags`;
- `review: {decision: pending, fixed_text: null, note: null}`.

Paraphrases: qwen3:4b-instruct-2507-q4_K_M via `LLMClient` (temperature 0, num_ctx 8192, seed 42),
three styles as in D5a, cache in `eval/questions/drafts/.cache/` (gitignored). The pick among the
unflagged candidates is index `sha256(salt + draft_id) mod n_clean`. With no clean candidate, the
template text stays and the row is flagged `no_clean_paraphrase`. The settings are recorded in
`eval/questions/drafts/paraphrase_manifest.json`.

## 4. Checks (`scripts/check_drafts.py`; also a CI test)

The script reads only the drafts, the gold side (spec, traps, pools, dev targets), corpus files (for
the absence and fact-line checks) and the set-E export. It checks:
- the schema;
- exact counts per type and split, and per bucket row;
- the hop, trap and wording distributions;
- that every gold node exists in the spec (test) or in the export (set E), and that `graph_sha256`
  matches the export;
- column disjointness from dev (targets, and dotted ids in question texts);
- no near-duplicates, against dev or within the drafts: equal normalised text, or token Jaccard
  ≥ 0.85 with dotted ids kept as single tokens;
- that unanswerable targets are truly absent from the corpus;
- that every Ask fact cites an existing non-blank `file:line`, and that stale-doc facts cite SQL;
- D5: at most 1 trace and at most 1 impact question per column.

`--allow-short` reports the counts still needed per type instead of failing on counts.

## 5. Review flow

1. `scripts/build_draft_review.py` writes `eval/questions/drafts/review/batch_1..6.csv`: stratified
   round-robin batches of about 47, each mixing test and set E. Each sheet has a matching
   `batch_N_gold.md` with the complete gold of its rows (A2). It also writes `REVIEW_GUIDE.md`.
2. The owner sets `decision` (keep / fix / drop) with `fixed_text` and `note`.
3. The owner runs `uv run python scripts/apply_draft_review.py` (A1). It writes `test_draft_v2.jsonl` /
   `external_draft_v2.jsonl` inside `eval/questions/drafts/` only, re-runs the checks with
   `--allow-short`, and prints the counts still needed per type. Replacement drafts for dropped rows
   are generated in a later session, from the gold spec only.
4. At the freeze, the owner writes `test.jsonl` / `external.jsonl` and their `.sha256` files, and
   applies the variance-subset rule (s13d §2.5).

Once the drafts are committed, a PreToolUse hook (`.claude/hooks/drafts_guard.py`) stops Claude Code
from reading, searching or running commands on them (A4). The owner lifts it for the freeze session.
