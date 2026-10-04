# Explain: the public demo (`src/dlens/ui/demo.py`, `demo/`)

Live at https://dlens-lineage.streamlit.app/. Operating steps are in `docs/deploy.md`; this file
explains the design.

## What it does
The demo is the normal UI (`src/dlens/ui/app.py`) in **demo mode** (`DLENS_DEMO=1`, forced by the
entrypoint `demo/streamlit_app.py`). It changes four things:

| Part | Local UI | Demo mode |
|---|---|---|
| Project | `corpora/*`, graph from `load_or_build` (runs dbt when stale) | `demo/synthetic_shop/graph.json` plus the 21 files it cites; no dbt, no `target/` |
| Model | Ollama, no budget | Gemini Flash-Lite (`DLENS_GEMINI_MODEL`) on the separate demo AI Studio project |
| Limits | none | 50 model calls/day app-wide, 5 live questions per session, 300 characters |
| Examples | dev questions, asked live | 10 **presets**: recorded runs replayed with no model call |

Everything else (agent loop, tools, validator, renderer) is the same code.

## How it works
- **Bundle.** `scripts/build_demo_bundle.py` saves the graph and copies only
  `demo.bundle_files(graph)`, the model/seed files and edge files the graph points at. These are
  exactly what the Source tab, `get_model_sql` and validator R3 read (through `safe_read`,
  relative to the project root). `graph.json` stores the dlens version, and `LineageGraph.load`
  refuses another version, so every release rebuilds the bundle. Uninstalled source trees read the
  version from `pyproject.toml` (Cloud runs `src/` without installing the package).
- **Install.** Cloud reads the dependency file next to the entrypoint before the root one, so
  `demo/requirements.txt` (exported from `uv.lock`, base + agent + ui minus dbt and groq) wins
  over the dev `uv.lock`. dbt is never imported on the demo path; it was only ever run as a
  subprocess on rebuild. CI job `demo-install` boots the demo from that file alone and clicks a
  preset.
- **Live questions.** `_ask` builds the environment with `demo.client_env`: the secrets (key,
  model ID), `GEMINI_DAILY_BUDGET=50`, and demo-only state, cache and run directories. Then it
  calls the usual `make_client("gemini", env)`. The 50/day cap is the existing `QuotaCounter`,
  so it is atomic and reserved *before* a call. `demo.gate` runs first: key present, ≤300
  characters, <5 live questions this session, and at least `MAX_LLM_CALLS` (8) calls left today,
  so a run is never cut off half-way. A mid-run `QuotaExceeded` or provider error becomes the
  same friendly state (`demo.failure`). The header slot is redrawn after the ask, so the count is
  current.
- **Presets.** `scripts/record_presets.py` runs the questions in `PRESET_IDS` on local Ollama
  against the bundle. It scores each run with the dev scoring and writes only passing runs as
  full `RunRecord`s. `demo.replay` re-runs the recorded tool calls on a fresh `Toolbox`, then
  takes the answer from `record.final_answer`. Tool calls are deterministic graph code, so the
  ledger (emitted ids, `r_` facts, citations) is rebuilt exactly, with no LLM client at all. Tests
  compare every replayed tool payload with the record and re-run the validator on each preset.

## Why this design
- **Same app, one flag.** A separate demo app would drift from the real one. The flag changes
  inputs (graph, provider, limits), never the pipeline.
- **Bundle, not dbt on Cloud.** dbt plus a DuckDB build on every cold start is slow and is a
  second thing to break. The graph is the product of the lineage engine, so ship that.
- **Replay tool calls, don't store the toolbox.** The record already holds every call and the
  graph is deterministic, so replay costs a few milliseconds. It also proves the preset still
  matches today's graph: if lineage changes, the payload comparison fails in CI.
- **Reuse `QuotaCounter`.** The cap uses the same reserve-before-send logic the dev budget
  relies on, and it is already tested.
- **Gate on a full run (8 calls).** Starting a question that the budget cannot finish would spend
  calls on an answer the user never sees.

## Alternatives rejected
- **Install the package on Cloud (`-e .`).** That pulls dbt-core and dbt-duckdb through the base
  dependencies. Putting `src/` on `sys.path` and reading the version from `pyproject.toml` keeps
  the install about 418 MB with no dbt.
- **Cached LLM responses for presets** (ship `llm.sqlite`). It would still run the agent and build
  a client, and a cache-key change would silently turn presets into live calls. Replaying records
  needs no client.
- **Use the dev key with a lower budget.** The demo project exists for isolation (spec §5); a
  public page must never spend the eval budget.
- **A persistent counter** (database, Cloud storage). It is more moving parts for a free demo.
  The container counter resets on reboot, and the demo project's own daily limit is the hard
  backstop (`docs/deploy.md`, "Known gap").
- **Per-IP limits.** They depend on proxy headers being trustworthy, and they make visitors on a
  shared network block each other. The per-session cap plus the app-wide cap bound the spend
  anyway.

## Explain-back questions
1. A visitor has 9 calls left today and asks a question that ends up needing 3 calls. Another
   visitor then sees "x of 50 left today". What number, and why could the first visitor's
   question start at all?
2. You change how `trace_upstream` formats a path string and release. Which tests fail, why, and
   what do you run to fix them?
3. Why can a preset show an `r_` reachability fact in the Source tab even though no `Toolbox`
   was stored in the preset file?
