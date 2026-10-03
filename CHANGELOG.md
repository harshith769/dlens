# Changelog

All notable changes to this project are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and the project uses
[Semantic Versioning](https://semver.org/) (pre-1.0: minor versions may change behaviour).

## [Unreleased]

### Added
- `dlens ask "question" [-p PROJECT] [--provider ollama] [--json]`: two-phase cited Q&A agent.
  The tool phase uses at most 5 LLM calls, with dedupe and token-budget compaction. The answer
  phase is rebuilt from the tool ledger with a JSON-schema answer. Citations are attached by
  code, ambiguous names are handled by chain / per-candidate / clarification, and there are at
  most 8 LLM calls per question.
- One JSONL draft record per run in `$XDG_STATE_HOME/dlens/runs` (override `DLENS_RUN_DIR`).
- `LLMClient.chat(..., response_schema=...)` for structured output (Ollama `format`, Gemini
  `response_json_schema`); part of the cache key only when set.
- Answer validator with rules R1–R7 and a safe id repair (R2r). It covers ids, citations
  re-checked on disk, hallucinated or unsupported nodes in prose, kind words versus edge kinds,
  citation relevance, and prose file/line references. On failure it regenerates once, then keeps
  only verified claims with `validation_warning`, or refuses. There are adversarial and
  hypothesis property tests. Results are in the run record and the `dlens ask` trace line.

- `get_model_sql(around_column=…)` follows in-model alias dependencies (CTE columns, up to 3
  hops) and returns ordered line windows, each with its own `excerpt_id`. For example,
  `dim_customers.lifetime_value` now shows the CTE line that computes it.

- Validator R8 (connectivity): a claim naming ≥2 columns must connect them through its cited
  edges. R2 now also checks (and safely repairs) ids written in prose.
- Salvaged answers rebuild `answer_text` from the kept claims whenever a claim is dropped, so
  a warned answer never states a rejected relationship.
- False-premise handling: a system-prompt line, and a code fallback that traces the named column
  when the model makes no tool call.
- Live fault injection for the validator's regenerate path
  (`scripts/smoke_agent.py --inject-bad-draft`, a script-only test hook) and two more dev smoke
  questions: a false premise and a 7-hop impact.
- Dev set: 20 questions on synthetic_shop in `eval/questions/dev.jsonl`, with gold taken from
  DESIGN.md and `lineage_spec.yml` lines (never parser output). `scripts/dev_report.py` scores
  them (dev-only, not the §11.4 metric; see `docs/explain/eval-dev.md`). `make eval-smoke` runs
  it on Ollama with the cache in `eval/cache`.
- Validator R8c (citation completion). A claim failing R8 gets the shortest directed path
  (≤4 hops per bridge) from this question's emitted edges. Conditions: one of its own cited
  edges must touch a column it names, and "direct(ly)" claims cannot get a bridge longer than
  one hop. Completed edges are re-checked by R3/R5/R7. Completions are recorded separately
  (`validation.completions`), and the benchmark reports claims as raw / repaired / completed.
  Built because completable R8 drops were 4/37 = 10.8% of first-draft claims on the dev set
  (decision threshold 10%, fixed in advance).
- Visible validation warning in `dlens ask` output: "⚠ Part of this answer couldn't be verified
  and was removed." when claims were dropped, and "⚠ No part of the answer could be verified."
  when the validator refused (that refusal now also sets `validation_warning`).
- Unknown-column refusal in code, before the tool phase. A dotted `model.column` whose model,
  seed or source exists but whose column does not is refused with "<model> has no column <col>"
  plus up to 3 closest columns, with no LLM call. CTE aliases, unique_ids and file names are
  never refused.
- Evidence guarantee. If the tool phase emitted no citable id, code runs `impact_downstream`
  (effect wording) or `trace_upstream` on up to 2 exact `model.column` ids named in the
  question, as `code` steps, then answers. This replaces the narrower "no tool call" fallback.
- `get_model_sql` accepts a `model.column` as `model_id` and splits it into model +
  `around_column`. An unknown model still returns `unknown_model`.

### Changed
- `get_model_sql` payload: `windows: [{excerpt_id, range}]` replaces `excerpt_id` /
  `excerpt_range`; `excerpt` holds `…` between windows.
- Agent tool specs are shorter (728 → 425 estimated tokens). They no longer advertise `k` or
  `include_indirect`, which the tools still accept.

## [0.1.0] - 2026-10-03

First public release: the lineage CLI.

### Added
- `dlens ingest`: runs dbt (build `--empty`, docs generate) and reads the manifest, catalog and
  compiled SQL into a schema-aware ingest result.
- Column-level lineage engine on sqlglot: direct edges with a kind (IDENTITY, RENAME,
  TRANSFORMATION, AGGREGATION), the expression, file and line range, plus parse quality per model.
- `LineageGraph` with upstream paths and downstream impact (columns, models, exposures).
- `dlens trace`, `dlens impact` and `dlens report` (`--json`).
- Graph cache at `target/dlens_graph.json`, rebuilt when the manifest or project sources change,
  or when the cache-format version or the DLens version differs.
- Golden tests per SQL construct and a generated construct support matrix
  (`docs/explain/lineage.md`), including untested gaps.
- Vendored example corpora: `jaffle_shop` and the trap-laden `synthetic_shop`.

### Known limitations
- DuckDB only; Python 3.12 and 3.13; dbt-core 1.12.x, dbt-duckdb 1.11.x.
- Only value dependencies are edges; join/filter/group/window keys are deferred.
- `SELECT *` over a join with duplicate column names is untested.

[0.1.0]: https://github.com/harshith769/dlens/releases/tag/v0.1.0
