# DLens — project memory for Claude Code

Full spec: docs/DLENS_SPEC.md (v1.6). Current plan: docs/plans/v0.3-plan.md.
Product direction: docs/plans/product-north-star.md. Read the relevant section before any task.

## What DLens is
An open-source Python tool (PyPI: `dlens-lineage`, CLI: `dlens`) with three parts:
- Column-level lineage for dbt projects (sqlglot on compiled SQL, with a catalog schema).
- An LLM agent that answers lineage questions with file/line citations checked by a code validator.
- A benchmark against vector RAG (S0–S4, C1).
Principle: code guarantees, the LLM narrates. If code can compute it, don't ask the model.

## Ownership model v2 (spec Section 17, ADR 0010)
- Claude Code writes the code. The owner approves every plan, owns design decisions, the gold data
  (corpus design, question review, freezes) and every tag.
- Every change to a module ships with an update to docs/explain/<module>.md: what it does, how it
  works, why this design, alternatives rejected, plus 3 explain-back questions. The owner must
  pass them before a tag (explain gate).
- Changes to src/dlens/lineage/, eval/metrics.py, the entity-linker scorer or the validator
  rules are allowed only when the approved plan names them. Metrics follow
  docs/plans/metrics-design.md exactly; definitions are the owner's decision.

## Hard rules
- Never edit eval/questions/test.jsonl, external.jsonl or their .sha256 files. Frozen.
  After the 7 Dec 2026 freeze, the S4 system (prompts, validator version, model IDs) is frozen too.
- Gold truth (lineage_spec.yml, question gold) is written from design docs, never derived
  from parser output. Draft it if asked; the owner approves it. Never auto-generate it from
  dlens's own lineage results.
- Never call a cloud LLM yourself. Gemini/Groq runs are commands the owner runs, after the owner
  confirms the quota plan. Never run `make eval-full` without explicit confirmation: it spends
  free quota. Check the quota counter first.
- All LLM calls go through dlens.agent.llm.LLMClient (token cap ~3K → cache → quota → rate
  limit → send). Default provider in development: Ollama (DLENS_PROVIDER=ollama).
- Never read or print .env. Never commit keys. Demo key lives only in Streamlit Cloud secrets.
- Only synthetic or public code is sent to free cloud APIs.
- Parse only compiled SQL from target/compiled, always with a catalog schema (or the documented
  catalog-less fallback, clearly marked).
- The LLM may only narrate tool results; the validator must pass.
- No absolute local paths or local usernames (e.g. /home/<user>/...) in committed files
  (demo/, docs/, reports). Public identifiers like the GitHub repo URL are fine.
- Diff is out of v1.0 scope. Don't add features outside spec Section 5. Product-track items
  (MCP server, PR bot) wait for v1.1+ unless the plan says otherwise. Never let product work
  block a research gate.

## Stack
Python 3.12 (CI also 3.13), uv, dbt-core 1.12.5 + dbt-duckdb 1.11.0, sqlglot 30.21.0, NetworkX,
bm25s, sentence-transformers (bge-small-en-v1.5, CPU), google-genai, ollama, Typer,
Streamlit (pinned >=1.65,<1.66), pytest, hypothesis, ruff, mypy.
v0.3 targets (still in pyproject until they land): numpy exact search replaces LanceDB (ADR 0014);
an OpenAI-compatible adapter replaces groq (ADR 0012).
Extras: agent, ui, retrieval (heavy; never in the demo install).

## Models
- Local (dev + second benchmark model): qwen3:4b-instruct-2507-q4_K_M via Ollama, num_ctx 8192.
- Cloud: gemini-3.5-flash-lite (versioned ID, never a -latest alias). Dev project budget
  400 calls/day; demo project capped at 50 calls/day in the app.

## Commands
- uv sync --extra agent --extra ui        # add --extra retrieval for v0.3 retrieval work
- make test          # unit + golden + property
- make lint          # ruff + mypy
- make ui            # local Streamlit
- make ingest CORPUS=synthetic_shop
- make eval-smoke    # cached dev questions, no quota
- make demo-requirements   # regenerate demo/requirements.txt from uv.lock
- make eval-full     # ASK FIRST
- Capped Gemini checks (owner runs them): scripts/smoke_llm.py, scripts/smoke_agent.py
  with --provider gemini --max-calls N --yes-spend-quota

## Demo rules
- Entrypoint demo/streamlit_app.py; bundle demo/synthetic_shop (graph.json + cited files);
  presets demo/presets/*.json recorded with LOCAL Ollama (scripts/record_presets.py).
- graph.json records the dlens version: a version bump and the graph rebuild go in the SAME
  commit. The demo-install CI job must pass.
- Corpus changes require rebuilding the bundle and re-recording presets (local, free).

## Conventions
- One planned unit per session (usually one plan item); plan first; small steps; a test with every change.
- Conventional commits; one commit per step (docs-only sessions may use one commit);
  run `make test` before each commit.
- The public interfaces in spec Section 7 are stable; propose changes as an ADR first.
- Visual changes: screenshot the UI (Playwright with Chromium) before and after.
- Environment: WSL2 Ubuntu; repo in ~/code/dlens; RTX 4050 (6 GB) used by Ollama.
  Conda is installed: always use `uv run` / `uv pip`, never bare `pip`.

## Current target
v0.3 Benchmark-ready + works on your own project (docs/plans/v0.3-plan.md), due 29 Nov 2026.
Test-set and system freeze: 7 Dec 2026. Update this line each release.
