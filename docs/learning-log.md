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
