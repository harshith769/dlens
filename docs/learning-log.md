# DLens learning log

## Week 0 — 3 Oct 2026
- Accounts done: GitHub (harshith769), Google AI Studio (dlens-eval, dlens-demo), Groq, dbt Learn, Streamlit, PyPI, TestPyPI.
- Measured: Gemini 3.5 Flash-Lite free tier = 15 RPM / 250K TPM / 500 RPD. Groq gpt-oss-120b = 30 RPM / 1K RPD / 8K TPM / 200K TPD.
- Local: qwen3:4b runs 100% on GPU at 61.7 tok/s; qwen3:8b spills to CPU (rejected).
- Pins: dbt-core 1.12.5, dbt-duckdb 1.11.0, sqlglot 30.21.0. jaffle_shop dbt build PASS=28.
- Lessons: Conda pip shadows the venv (use uv only); Ollama `/set nothink` disables thinking; WSL RAM had to be raised via .wslconfig.
- Full details: docs/setup/week0-report.md

## Pre-work Task 2: dbt fundamentals, 3 Oct 2026
- Built customer_segments (table) + 4 tests + an exposure on jaffle_shop; broke a test on purpose.
- Key facts for DLens: ref() compiles to a 3-part relation name; manifest.json relation_name maps it back
  to the node id; catalog.json gives column types (needed for sqlglot schema / SELECT * expansion);
  parse target/compiled, never source or target/run; manifest includes test nodes, so filter them.
- Lesson: accepted_values would NOT catch NULLs hidden by `else 'loyal'`; tests only catch what they check.
- Full notes: ~/scratch/prework/task2_dbt/NOTES.md

## Pre-work Task 2: dbt fundamentals, 3 Oct 2026
- Built customer_segments (table) + 4 tests + an exposure on jaffle_shop; broke a test on purpose.
- Key facts for DLens: ref() compiles to a 3-part relation name; manifest.json relation_name maps it back
  to the node id; catalog.json gives column types (needed for sqlglot schema / SELECT * expansion);
  parse target/compiled, never source or target/run; manifest includes test nodes, so filter them.
- Lesson: accepted_values would NOT catch NULLs hidden by `else 'loyal'`; tests only catch what they check.
- Full notes: ~/scratch/prework/task2_dbt/NOTES.md

## Pre-work Tasks 3-6: artifacts, sqlglot, NetworkX, tool calling, 3 Oct 2026 (fast mode)
- Task 3: manifest = depends_on + compiled SQL + relation_name; catalog = columns + types. Seen renames (user_id -> customer_id) and cents -> dollars.
- Task 4: SQL -> AST; lineage(None) on compiled orders.sql gave per-column sources. No schema -> UNKNOWN(amount); with schema -> payments.amount. sqlglot stops at the model boundary (DLens stitches models) and misses join keys (DLens adds indirect edges in v0.3).
- Task 5: column graph in NetworkX; upstream = trace, downstream = impact, cutoff = max hops.
- Task 6: tool loop works on qwen3:4b and gemini-3.5-flash-lite. Qwen duplicated a tool call and leaked <think>, so DLens needs dedupe, a step cap, think-stripping and a structured answer schema. Use a manual loop (not SDK auto) to fit cache/quota/validator.
- Decision 17: AI writes code; I review/approve; core modules get docs/explain/.
- Pre-work done in one afternoon; v0.1 pulled forward to 18 Oct.

## 2026-10-03 — v0.1.0 released
- Shipped dlens-lineage 0.1.0 to PyPI, 15 days ahead of plan.
- Trusted Publishing: GitHub Actions gets a short-lived OIDC token that PyPI trusts for this repo + workflow + environment, so no API token is stored anywhere.
- Release order: build once → TestPyPI → install in a fresh venv and run `dlens --version` → human approval → PyPI. The same artifact goes to both indexes, so what was tested is what ships.
- A PyPI version number can never be re-uploaded, which is why the TestPyPI rehearsal and the tag == pyproject version check exist.
- Attestations: PyPI stores signed provenance linking the file to the workflow run that built it.
- Caveat I must state in interviews: F1 1.000 is on our own synthetic corpus; real validation is v0.3 (bigger corpus) and v1.0 (public project + colibri).

## 2026-10-03 — v0.2 sessions 1–4: LLM gateway, tools, agent loop, validator
- LLMClient: every LLM call goes through cache → quota (Gemini 400/day, Pacific-midnight reset) → rate limit → 3K-token cap. Cache hits cost nothing.
- Switched local model to Qwen3-4B-Instruct-2507: the qwen3:4b tag was the thinking-only build (bare </think> = template-inserted <think>).
- Gemini 3 gotchas: thought signatures must be replayed in tool-calling history (else 400); keep temperature 1.0; reproducibility comes from the cache.
- Tools return compact strings to the LLM; full citations stay in a side record; code attaches file:line from ids, so the LLM never types a line number.
- Two-phase loop: tool phase (≤5 calls, compaction keeps ids) + answer phase rebuilt from the ledger with a JSON schema. Max call 2,152 of 3,000 tokens.
- Ambiguity handled in code: same-lineage-chain names → answer for the most downstream; unrelated → per-candidate or clarification.
- Validator R1–R8 + R2r: cites, in-ledger (+ unique 1-edit repair), on-disk, known nodes, kind words, prose refs, relevance (anti-laundering), connectivity (no skipped hops). Regenerate once, then salvage; zero false positives on smoke.
- Lesson: don't rely on a 4B model for what code can guarantee (ambiguity, refusals, false-premise tracing, citations).

## 2026-10-04 — v0.2 UI v2: redesign of the local Streamlit app
- Three tabs: Ask (cited answer), Explore lineage (no LLM, no quota) and How it works (pipeline, nine rules, dev score labeled as the 20-question dev set, not the benchmark).
- The signature element is a column-level lineage diagram: Graphviz DOT, one cluster per layer, a table node per model with column ports, and edges colored by kind with a short expression. A model-level graph can't show which column feeds which.
- Badges only from real fields: verdict (answered / refused / clarification / chain mode) and verification (verified / repaired / completed / regenerated / partially removed). I deferred "Corrected premise" because the agent has no signal for it; a UI heuristic would be a guess the validator never checked.
- Streamlit 1.65 has stateful tabs (`key` + `on_change="rerun"`), so a citation chip can open the Source tab from code. The theme font option takes Google Fonts URLs, so no CSS @import is needed.
- Safety rules for a UI that renders model output: escape everything shown as HTML (tested with `<script>`), read files only through `safe_read` (never outside the project), and export only project-relative paths.
- Lesson: keep `view.py` free of Streamlit. 46 UI tests (pure helpers plus AppTest smoke tests per tab with a scripted fake LLM) run in about 3 s, with no browser and no Ollama.

## 2026-10-04 — v0.2.0: public demo on Streamlit Community Cloud
- Live at https://dlens-lineage.streamlit.app/. It is the same app as `make ui`; `DLENS_DEMO=1` swaps the inputs (prebuilt graph, Gemini, caps), never the pipeline.
- Ship the graph, not the build: `demo/synthetic_shop/graph.json` plus only the 21 files it cites. No dbt on Cloud. `graph.json` stores the dlens version, so every release rebuilds the bundle (the 0.2.0 rebuild changed exactly that one line).
- Streamlit Cloud reads the dependency file next to the entrypoint before the root one: `demo/requirements.txt` (exported from `uv.lock`, without dbt) beats the dev `uv.lock`. About 418 MB, mostly pyarrow from Streamlit; no torch.
- Bug found only by booting from a clean venv: an uninstalled `src/` reported version `0+unknown`, so the version-stamped graph refused to load. Fix: read `pyproject.toml`. Lesson: test the real install path; CI job `demo-install` now does it on every push.
- Caps reuse `QuotaCounter` (reserve before send): 50 calls/day app-wide, 5 per session, 300 characters, and start only if a full 8-call run fits. Known gap: the container's disk is not persistent, so the counter resets on reboot; the demo AI Studio project's own daily limit is the backstop.
- Presets are replayed run records, not cached LLM responses. The tool calls are re-run on the graph (deterministic), so no client is built. Tests compare every tool payload with the record and re-run the validator, so a lineage change that breaks a preset fails CI.
- dev-11 failed recall twice when re-recorded fresh, after passing in dev_r9: a 4B model is not deterministic across runs. I swapped in dev-13 (also "computed") instead of relaxing the pass rule.
- Live check: the title and the "x of 50 left today" status sat under Cloud's toolbar. They were invisible in AppTest and only showed up in a real browser screenshot, so demo mode now adds top padding.
- Seen live on Gemini: a two-part question ("…come from? can i remove it?") came back Answered + Partially removed. The validator did its job, but the user should hear "I can't answer that part". That is v0.3 backlog, together with a `premise_corrected` field (ADR).
