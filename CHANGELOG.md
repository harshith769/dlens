# Changelog

All notable changes to this project are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and the project uses
[Semantic Versioning](https://semver.org/) (pre-1.0: minor versions may change behaviour).

## [Unreleased]

### Changed
- **`groq` left the `agent` extra** (ADR 0012); Groq is now a preset of the OpenAI-compatible
  adapter (`httpx`, already installed). `eval/metrics.py` 1.2.0: an S1 record adapter and the
  ADR 0024 verdict accessor, with no metric definition changed (metrics-design stays v1.1).
- **Entity linker v2** (`resolve_entity`, S08; ADR 0022, docs/plans/linker-design.md): stage 1
  exact matches always rank first; stage 2 surface / rewritten (plural, an 18-entry abbreviation
  table, phrase rules "number of / how many / count of / total X", weak `usd`, word order) /
  bounded fuzzy, with a model-named-in-the-text bonus and a small layer prior; stage 3 hybrid over
  column cards when the `retrieval` extra and a built index are present. No-match below 0.60
  (`candidates: []`); ambiguity margin 0.05 unchanged. Payload additions: `match: "hybrid"` and an
  optional `hybrid` key; score parts and `closest` stay in the side record.
- **Dotted ids** (`model.column`): resolved exactly, or through the abbreviation table alone to
  exactly one column of that model, by one function shared with the loop's unknown-column
  refusal; code prefixes the answer with "Interpreted X as Y.".

### Added
- **S1 vector-RAG baseline** (S11; docs/plans/s1-design.md): `eval/systems/s1.py` and
  `make eval-s1`. Hybrid search on the raw question over the S07 index, chunks skip-and-packed
  into the 3K cap minus a repair reserve, S4's answer-phase instructions plus three S1 lines
  (frozen and snapshot-tested), citations attached by code from the shown chunks, no validator.
  Cloud providers are refused without `--allow-cloud`. Smoke run on the 96 dev questions with
  local qwen3:4b: `eval/reports/s1_smoke_dev.md`, health and retrieval diagnostic in
  `s1_smoke_dev_health.md` (`scripts/s1_diagnostics.py`), summary beside S0 in
  `eval/reports/s11_session.md`.
- **OpenAI-compatible LLM adapter** (S11, ADR 0012): `DLENS_PROVIDER=openai` for any
  `/chat/completions` endpoint (OpenRouter, LM Studio, vLLM, OpenAI, Ollama's `/v1`);
  `DLENS_PROVIDER=groq` is a preset of it. The base URL is part of the cache key. The API key is
  read at send time only and never stored, cached, logged or put in error text. A non-local
  endpoint needs a key and a daily call budget.
- **`Answer.reach_verdict` / `reach_verdict_source`** (ADR 0024, additive): the structured yes/no
  verdict metrics scores, and who set it. S4 adopts it in S12.
- **Citation audit** (`scripts/citation_audit.py`, `eval/reports/citation_audit.md`): the
  ledger citation helper also cites a YAML description from its entry's `- name:` line, so the
  cited lines name the column or model (110 column cards, 49 model descriptions). S1 was re-run
  under that rule (B8 freeze change), and v2 is the frozen S1.
  Star pass-through column cards whose column is named nowhere in the statement (16) are cited
  at `level: star`, as S4 cites them; the v2 records' levels were re-attached without an LLM call
  (`scripts/s1_reattach_citations.py`) and re-scored.
- **Shared run-manifest writer** `eval/systems/manifest.py` (S0, S1; S4 in S12) and the
  seed-card citation helper `dlens.retrieval.citation` (a seed column card is cited at its CSV
  header line).
- **Benchmark metrics v1** (S10; ADR 0023, docs/plans/metrics-design.md v1.0): `eval/metrics.py`
  scores run records of any system the same way: a shared prose extractor (identifier filter,
  tested negation rule, CTE references apart), node-set F1 in each question's primary mode with
  both modes reported, structured yes/no verdicts only, false-premise rejection, path node
  coverage, hallucinated-node rate, on-disk citation re-check, seeded bootstrap CIs, paired
  bootstrap and exact McNemar. It never imports the system under test.
- **S0 graph oracle** (`eval/systems/s0.py`, `make eval-s0`): S0-gold and S0-linked (hybrid off),
  no LLM, records in the S4 run-record format under `eval/runs/s0/`; reports
  `eval/reports/s0_dev.md`. The S09 S4 smoke records were re-scored, report only
  (`eval/reports/s4_smoke_dev.md`).
- **Linker test set** `eval/linker/` (247 owner-reviewed cases, split linker-dev / linker-test by
  gold column; dev mentions; a 20-mention dbt_jira sample), `scripts/gen_linker_cases.py`,
  `scripts/linker_report.py` (`eval/reports/linker.md`), `scripts/linker_preset_gate.py`, and
  `scripts/dev_report.py --hybrid` with a run manifest.
- **Agent rule `linked_evidence`** (S08, owner decision): for where-from / how-computed / impact
  questions, when resolve_entity linked exactly one unambiguous column and no trace/impact ran
  on it, code runs the matching tool (0 LLM calls). Every code-initiated tool call is now tagged
  `code_initiated: true` with its `rule` in the ledger and the run record.
- **Citation coverage** in `dlens ingest --artifacts` and `dlens report` (text and `--json`):
  line-level vs model-level citations for SQL-model columns, direct and indirect edges, with the
  model-level ones grouped by reason (no project files, file not found, SELECT built by a macro or
  Jinja, clause key written by a macro or Jinja, clause not in the source). Seed and source
  columns are counted apart: they always cite a whole CSV or YAML file.
- **Hybrid retrieval** (`retrieval` extra; ADR 0014, ADR 0021): chunks of model SQL (split at
  CTE boundaries, on source `.sql` lines), column cards (name, type, YAML description) and doc
  chunks (descriptions, `{% docs %}` blocks, exposures, README). Each chunk has file, lines and
  line basis. Search is BM25 (`bm25s`) plus `BAAI/bge-small-en-v1.5` on onnxruntime at a
  pinned revision, fused with RRF (k = 60), over exact numpy search. Only files the manifest
  names are indexed, and graph facts never enter indexed text. The index is cached next to the
  graph and says why it rebuilt.
- `dlens search "<query>" [--project DIR | --artifacts TARGET]` with `--k`, `--kind`, `--mode`,
  `--rebuild`. The model downloads once (~133 MB) into the Hugging Face cache; `HF_HUB_OFFLINE=1`
  runs fully offline afterwards.
- `search_docs` tool (capped at 1,500 tokens; YAML/README text returned as quoted, possibly
  stale data). It is not yet used by `dlens ask` (v0.3, S12).
- **Artifact-only ingest** (ADR 0013): `dlens ingest --artifacts target/` builds the graph from
  an existing dbt `target/` (manifest.json, optional catalog.json, compiled SQL) with no dbt run,
  no warehouse connection and no network. The dialect comes from `adapter_type` (duckdb,
  snowflake, bigquery, postgres, redshift, databricks, spark, trino; `--dialect` overrides).
  Manifest v12 is supported (dbt 1.8 to 1.12 and 2.0); any other version is a clear error. The
  graph is cached in `target/dlens/` (or `--out`) and reused while the manifest and catalog
  hashes match. `trace`, `impact` and `report` take `--artifacts target/`.
- Catalog-less fallback: without catalog.json, columns come from YAML declarations, and each
  parsed model's output columns feed the models after it. A `*` over an undeclared table is a
  gap. `dlens ingest` prints FULL / PARTIAL / TABLE_ONLY / FAILED counts with reasons.
- Ephemeral models appear in the lineage under their own name and columns, instead of being
  skipped through their `__dbt__cte__` CTE.
- Dialect round trip test: synthetic_shop transpiled to Snowflake, BigQuery and Postgres keeps
  direct and indirect edge F1 within 0.02 of DuckDB (`scripts/dialect_check.py`,
  `eval/reports/s06_dialects.json`).
- Set-E corpus: [fivetran/dbt_jira](https://github.com/fivetran/dbt_jira) v1.10.2 vendored in
  `corpora/dbt_jira` (Apache-2.0; `SOURCE.md` lists every local change), built offline with
  dbt-duckdb. 61 models, 13 of them ephemeral; 60 FULL, 1 PARTIAL. It is not in the wheel or sdist.
- CI: a core install (no extras) on macOS and Windows runs `dlens ingest --artifacts` on a
  committed fixture. Every `uv sync` step retries once on transient download errors.
- Perturbation oracle (`make oracle`, `eval/oracle/`, ADR 0017): an independent dynamic check of
  the synthetic_shop gold. It perturbs each column in DuckDB, re-runs the compiled SQL (one hop
  and end to end) and compares the changed columns with `lineage_spec.yml`. Result: 0
  disagreements the gold misses, 762 of 907 one-hop pairs observed, and every unobserved pair
  auto-tagged or decided by the owner (`ORACLE_REPORT.md`, `oracle_exceptions.yml`). The
  integration test re-runs it (about 40 s).
- `dlens trace ... --include-indirect` and `dlens impact ... --include-indirect` (default off):
  traversal also follows indirect edges (JOIN, FILTER, GROUP_BY, WINDOW, SORT, CONDITIONAL),
  and each indirect hop is marked with its type, its clause and the clause's `file:lines`.
  Without the flag the output is unchanged. `LineageGraph.upstream`/`downstream` honour
  `include_indirect` (spec §7 defaults). The agent tools, validator, UI and demo stay
  direct-only.
- Indirect edges cite their clause's lines in the model's source file (JOIN ON / USING, WHERE,
  HAVING, QUALIFY, GROUP BY, ORDER BY, OVER, FILTER (WHERE), aggregate ORDER BY), using the same
  file and line numbering as direct edges. A clause that can't be located falls back to the
  whole file, and `dlens report` shows why (`citation gap`).
- Indirect-edge gate: F1 ≥ 0.90 on synthetic_shop (`compare_gold.py --indirect` exits 1 below
  it). `scripts/measure_indirect_reach.py` measures what indirect traversal does to impact size.

### Changed
- The `retrieval` extra is now `bm25s`, `onnxruntime`, `tokenizers`, `huggingface-hub` and
  `numpy`. torch, sentence-transformers and lancedb are gone (a plain pip install adds ~176 MB
  instead of ~6 GB of CUDA torch; ADR 0021).
- A FILTER or JOIN key computed by a window function in an inner query (`where rn = 1` over
  `row_number() over (...) as rn`) now resolves to the window's PARTITION BY / ORDER BY columns
  plus its value arguments, matching QUALIFY (ADR 0020, S06 clarification). Before, it resolved
  to nothing.
- Graph format v4: adds `citation_gaps` to the parse report and drops `deferred_indirect` (window
  keys are WINDOW indirect edges). Reads v2–v4, so the demo bundle (v2) loads unchanged, and
  older caches are rebuilt.

### Fixed
- Package models (e.g. every dbt_jira model) cite lines in their own files under
  `<packages-install-path>/<package>/` instead of the whole file. Lineage and the chunker share
  one resolver (`dlens.ingest.paths`). A package that `dbt deps` installed as a symlink is
  followed only for files the graph references, and only if the package root's `dbt_project.yml`
  names that package. Graph format unchanged; artifact caches carry `builder_version` 2, so
  caches built before the fix rebuild.
- A WHERE over a derived-table column (`... ) as t where t.amt > 100`) now cites its own lines
  instead of falling back to the whole file.
- A source declared over a seed's table (both claim one relation) no longer stops ingest: the
  relation maps to the source, which is what models read. Any other collision is a clear error.
- On Windows, `dlens trace`/`impact` no longer crash with UnicodeEncodeError when output is piped
  or redirected; the CLI writes UTF-8.
- Edge kind follows each input's own path: a scalar subquery's aggregate no longer makes a
  sibling column AGGREGATION, and `sum(sum(x)) OVER (...)` is AGGREGATION.
- `SELECT * EXCLUDE (...)` / `* REPLACE (...)` / `t.* EXCLUDE (...)` columns cite the star's line
  instead of the whole model.

## [0.2.0] - 2026-10-04

The cited Q&A agent, a local UI and a public demo at https://dlens-lineage.streamlit.app/.

### Added
- Public demo on Streamlit Community Cloud (`demo/`, `docs/deploy.md`, `docs/explain/deploy.md`).
  `DLENS_DEMO=1` (forced by `demo/streamlit_app.py`) makes the UI read a prebuilt
  `synthetic_shop` bundle: `graph.json` plus only the files it cites, with no dbt and no
  `target/`. Live questions go to Gemini Flash-Lite on a separate AI Studio project. Caps:
  50 model calls a day app-wide (`QuotaCounter` in a demo-only state dir), 5 live questions per
  session and 300 characters; a question starts only if a full 8-call run still fits. Limits
  show a friendly "Demo limit reached, try a preset" state, and the header shows "x of 50 left
  today". The key comes from Streamlit secrets and is never shown or logged.
- 10 demo presets (`demo/presets/*.json`): full run records made with local qwen3:4b by
  `scripts/record_presets.py`, which writes only runs that pass the dev scoring. The UI replays
  the recorded tool calls on the graph with no LLM client, under a "Precomputed with local
  qwen3:4b" badge and a short tag per preset. Tests re-validate each preset offline.
- `demo/requirements.txt` (`make demo-requirements`, exported from `uv.lock`): the light Cloud
  install, base + agent + ui without dbt or groq, about 418 MB. CI job `demo-install` boots the
  demo from that file alone and replays a preset.
- Capped live smokes the owner runs: `scripts/smoke_llm.py --provider gemini` (text, JSON, tool
  call; hard cap 10) and `scripts/smoke_agent.py --provider gemini` (dev-01 and dev-10 end to end;
  hard cap 16). Both need `--yes-spend-quota`, use the dev key and dev quota counter, and print
  the counter before and after.
- Local Streamlit UI (`make ui`, extra `ui`), Ollama only, with three tabs.
  - **Ask:** verdict and verification badges, per-claim ✓/⚠ with citation chips, and detail tabs:
    Lineage (a layered column-level diagram), Source (highlighted cited lines), Steps and Checks.
    Also session history and Markdown/JSON export.
  - **Explore lineage:** no LLM.
  - **How it works:** the pipeline, the rules and the dev score.

  Light theme with IBM Plex fonts. See `docs/explain/ui.md`.
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
- Reachability fact and validator R9. For a yes/no question naming exactly 2 exact columns with
  affect/impact/depend/feed/flow/reach/change wording, code checks graph reachability both ways
  and emits a citable `r_` fact plus the shortest path's edges. R9 requires the answer's yes/no
  verdict (first sentence, heuristic) to match. On failure the answer is regenerated once with
  the fact; if it still fails, salvage states code's verdict citing `r_`, with
  `validation_warning`. `r_` ids work in R2/R3/R7/R8 and render as `[graph check]`. This fixes
  dev-10 (a wrong "Yes" that passed validation): dev pass is 18/20.

### Changed
- A source tree that is not installed reads its version from `pyproject.toml` instead of
  reporting `0+unknown` (the demo runs `src/` uninstalled).
- UI history labels are clipped in the middle, so questions with the same start stay distinct.
  The dev score is labeled "Dev set: 20 hand-written questions, local qwen3:4b (not the
  benchmark)".
- `.streamlit/secrets.toml` is ignored at any depth.
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

[Unreleased]: https://github.com/harshith769/dlens/compare/v0.2.0...HEAD
[0.2.0]: https://github.com/harshith769/dlens/releases/tag/v0.2.0
[0.1.0]: https://github.com/harshith769/dlens/releases/tag/v0.1.0
