# DLens — project memory for Claude Code

Full spec: docs/DLENS_SPEC.md (v1.3). Read the relevant section before any task.

## What DLens is
An open-source Python tool with three parts:
- Column-level lineage for dbt projects (sqlglot on compiled SQL).
- An LLM agent that answers lineage questions with file/line citations checked by a validator.
- A benchmark against vector RAG (S0–S4, C1).

## Hard rules
- Never write code in src/dlens/lineage/ or eval/metrics.py, nor the entity-linker scorer
  or the validator rules, unless the owner explicitly asks. The owner writes these by hand.
  You may add tests and refactor on request.
- Never edit eval/questions/test.jsonl, external.jsonl or their .sha256 files. They are frozen.
- Never run `make eval-full` or any non-cached cloud LLM run without explicit confirmation:
  it spends free quota. Check the quota counter first.
- All LLM calls go through dlens.agent.llm.LLMClient (cache + rate limiter + quota counter
  + about 3K input-token cap). The default provider in development is Ollama (DLENS_PROVIDER=ollama).
- Never read or print .env. Never commit keys.
- Parse only compiled SQL from target/compiled, always with a catalog schema.
- The LLM may only narrate tool results; the validator must pass.
- Diff is out of v1.0 scope. Don't add features outside spec Section 5.

## Stack
Python 3.12, uv, dbt-core 1.12.5 + dbt-duckdb 1.11.0, sqlglot 30.21.0, NetworkX, LanceDB,
bm25s, sentence-transformers (bge-small-en-v1.5), google-genai, ollama, groq, Typer,
Streamlit, pytest, hypothesis, ruff, mypy.

## Commands
- uv sync
- make test          # unit + golden + property
- make lint          # ruff + mypy
- make ingest CORPUS=jaffle_shop
- make eval-smoke    # 30 cached dev questions, no quota
- make eval-full     # ASK FIRST

## Conventions
- One checklist item per session; plan first; small steps; a test with every change.
- Conventional commits. Run `make test` before proposing a commit.
- The public interfaces in spec Section 7 are stable; propose changes as an ADR first.
- Environment: WSL2 Ubuntu; repo lives in ~/code/dlens; GPU is an RTX 4050 (6 GB) for Ollama;
  local model qwen3:4b (dev and benchmark). Gemini: versioned Flash-Lite ID, 400 calls/day budget. Conda is installed: always use `uv run` / `uv pip`, never bare `pip`.

## Current target
v0.1 Lineage CLI (spec Section 14). Update this line each release.
