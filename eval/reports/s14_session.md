# S14 session report: local UI on any ingested project (E2) + public-project coverage (E4b)

**Date:** 24 Oct 2026. **Branch:** `s14-ui-coverage` from main 08986c2 (not merged; the owner
merges). **Plan:** the approved S14 plan with owner amendments A1–A5 and the gate fixes.
Product track only: the research system is unchanged.

## Status

| item | state |
|---|---|
| E2 step 1: project-mode helpers | done, 6fa0308 |
| E2 step 2: `dlens ui --project` CLI | done, a29a2b5 |
| E2 step 3: project-mode tabs in `app.py` | done, 5c6f7de |
| E2 step 4: docs (explain, README, CHANGELOG) | done, f0dea34 |
| Owner screenshot gate | reviewed; 3 fixes + the key line done in 822748a; affected screenshots re-taken |
| E4b: public-project coverage | done, b286a8d: 5 projects, 1 sqlglot repro |
| Agent sha | `bfcf97d5d56c8d873189bdcf68a62666bb095868d34ad23e1ac2aa998537aef5` (unchanged) |
| Cloud LLM calls | **0**. No `--allow-cloud`, no `.env` read; tests use stub providers only |
| Frozen question files | not opened |
| CI | see "CI" below |

## Flow
1. Plan, then owner amendments A1–A5: loopback launch without telemetry; Ask isolated from the
   benchmark (fresh env, no ambient key, its own budgets, files under `target/dlens/ui/`);
   Playwright only in a scratch environment; the dbt_jira Ask uses the stub only; A5 checks
   after the gate.
2. E2 built in 4 commits, then STOP at the screenshot gate.
3. Owner review asked for: the Trace / Impact default column, the dbt project name, paths in
   captions and hints, and a key-storage line. Done in one commit with tests. Explore and
   Trace / Impact were re-taken for both projects; the two scratch servers were stopped.
4. E4b in a scratch dir, then this report, then push.

## What E2 delivers
- `dlens ui --project DIR [--artifacts TARGET] [--port N] [--host H]`. It checks Streamlit
  first (prints `pipx install "dlens-lineage[ui]"` / `pip install "dlens-lineage[ui]"`), then
  that the project is ingested (prints the exact commands), then runs Streamlit on 127.0.0.1,
  headless, with usage statistics off. `--host` warns. `DLENS_DEMO` is never passed on.
- The same `app.py` in project mode, with the tabs **Explore** (coverage levels, models worst
  first, columns), **Trace / Impact** (diagram, cited edges, the CLI's path text and command),
  **Source** (read-only, graph files only, compiled SQL), **Ask** and **How it works**. The
  privacy line is on every page, the not-ingested page included.
- **Ask** calls the existing `loop.ask` with S4's `Toolbox(graph, project_dir, index)`. With no
  retrieval extra or no index it uses the graph tools only and says so. Providers: Ollama
  (default), Gemini, OpenAI-compatible. A key comes only from the password box or a named env
  var. The env per ask is a fresh dict (never `os.environ`) with cache, quota and runs under
  `target/dlens/ui/`, and each cloud provider has a daily budget (default 50). Errors, refusals,
  history and run logs are redacted (`RedactingRunLogger` lives in the UI package, so agent code
  is untouched). Removed claims are shown.
- The demo and `make ui` modes are unchanged: the existing demo and app tests pass unchanged.

## Tests
- New: `tests/unit/agent/ui/test_project.py` (23), `tests/unit/agent/ui/test_project_app.py`
  (10, Streamlit AppTest), `tests/unit/test_cli_ui.py` (5). They cover:
  - project loading and the not-ingested, stale and no-artifacts hints;
  - path safety (`../`, absolute, symlink escape, non-graph file);
  - launch flags and `--host`;
  - the no-LLM tabs with no model built;
  - Ask with a stub provider through the real client wiring (cache and quota paths), including
    validator removals;
  - files under `target/dlens/ui/` only, with nothing under `eval/` or the default XDG paths;
  - the ambient `GEMINI_API_KEY` never being used, and a named env var being used but never
    shown;
  - a sentinel key absent from the rendered output, the user session state, every file under
    the project and HOME, and the cache and quota sqlite files, including a provider that echoes
    the key and an exception carrying it;
  - in subprocesses: `import dlens.cli` + `dlens ui` with streamlit, ollama, google, httpx,
    bm25s, onnxruntime and tokenizers blocked; and the whole app with ollama, google.genai,
    httpx, bm25s, onnxruntime and tokenizers blocked (Explore / Trace / Source render, Ask shows
    the install hint, no blocked module loaded).
- `make lint` and `make test` passed before every commit. Last run: **1726 passed, 19 skipped**
  (1688 before S14).

## Frozen checks
- `git diff 08986c2 -- src/dlens/agent src/dlens/lineage src/dlens/retrieval eval/metrics.py
  eval/systems eval/questions` is **empty**.
- `s4.agent_code_sha256()` = `bfcf97d5…aef5` (pinned by `tests/unit/eval/test_s4.py`).
- `s1.frozen_hashes()` is unchanged (pinned by its test): system `fb820558…`, user_template
  `b85d5465…`, evidence_rule `56973cf4…`, schema `60364350…`, repair `cc417eb2…`, clarification
  `40fd7a42…`, citation_rule `159a0020…`, budget_rule `c2ec079e…`.

## Screenshot gate (A4, A5)
- synthetic_shop: `dlens ui --project <scratch>/synthetic_shop --port 8601`; Ask on real local
  Ollama (Answered, Verified, 5 cited claims).
- dbt_jira: `python -m streamlit run <scratch stub launcher>` with the same four flags, on
  port 8602; Ask with the stub provider only ("What does this project contain?"). The stub
  launcher was never committed.
- Both bound to `127.0.0.1` only (`ss -ltnp`). Nothing was written under `eval/`
  (`git status --porcelain eval/` empty; `find eval -newer <stamp>` empty). Nothing new
  appeared in `~/.local/state/dlens/runs`.
- Playwright and Chromium came from a scratch venv; nothing was added to pyproject.toml or
  uv.lock. The Playwright MCP could not start (no Chrome installed), so it was not used.

## E4b coverage summary (`docs/real-world-coverage.md`)

| Project | Models | FULL | PARTIAL | TABLE_ONLY | FAILED | Catalog |
|---|---:|---:|---:|---:|---:|---|
| jaffle_shop | 5 | 100% | 0 | 0 | 0 | full |
| tw_campaign_finance | 4 | 75.0% | 0 | 1 | 0 | partial |
| danish-democracy-data | 26 | 80.8% (96.2% catalog-less) | 0 | 5 | 0 | partial |
| nba-monte-carlo | 68 | 61.8% | 12 | 9 | 5 | partial; target outside the project |
| dbt_jira (set E) | 61 | 98.4% | 1 | 0 | 0 | full |

- All 5 succeeded, each well within the 30-minute time box. Excluded: Datadex (no dbt project at
  the current commit), SOMA (no licence file), and the warehouse-only / >300-model projects.
- **sqlglot:** one minimal reproduction, `docs/upstream/0001-sqlglot-lineage-union-star-index.md`
  (`lineage()` on a UNION whose branch is `SELECT *` over an unknown table raises for column
  index ≥ 1, but not for 0). **Not filed**; the owner files it.
- No questions or gold were created from any project, and nothing from them is committed.

## Carry-forward
1. **Python models** (nba-monte-carlo, 4 models) are parsed as SQL and counted FAILED. They
   should get a clear "Python model: no SQL lineage" reason. This needs a plan that names
   `src/dlens/lineage` (or the ingest step).
2. **A partial catalog is worse than none** (danish: 21 vs 25 FULL). The YAML-declared columns
   should be used per relation when the relation is missing from `catalog.json`.
3. **`target-path` outside the project** gives whole-file citations; `dlens ingest` could take
   the project folder explicitly.
4. **The sqlglot workaround** for repro 0001 (treat the error as an unexpanded-`*` gap) is
   lineage code, so it waits for a plan.
5. **UI ideas not built:** a "both" direction in Trace / Impact; jumping from Explore's model
   table to Source.
6. **Explain gate:** `docs/explain/ui.md` has three new explain-back questions (4–6, project
   mode) for the owner before the v0.3 tag.
7. **Demo:** unchanged. The S15 re-recording of presets is still pending (the existing skip
   list).

## CI
Pushed after this report; result in the PR / branch checks (see the owner summary).
