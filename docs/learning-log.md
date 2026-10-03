# DLens learning log

## Week 0 — 3 Oct 2026
- Accounts done: GitHub (harshith769), Google AI Studio (dlens-eval, dlens-demo), Groq, dbt Learn, Streamlit, PyPI, TestPyPI.
- Measured: Gemini 3.5 Flash-Lite free tier = 15 RPM / 250K TPM / 500 RPD. Groq gpt-oss-120b = 30 RPM / 1K RPD / 8K TPM / 200K TPD.
- Local: qwen3:4b runs 100% on GPU at 61.7 tok/s; qwen3:8b spills to CPU (rejected).
- Pins: dbt-core 1.12.5, dbt-duckdb 1.11.0, sqlglot 30.21.0. jaffle_shop dbt build PASS=28.
- Lessons: Conda pip shadows the venv (use uv only); Ollama `/set nothink` disables thinking; WSL RAM had to be raised via .wslconfig.
- Full details: docs/setup/week0-report.md
