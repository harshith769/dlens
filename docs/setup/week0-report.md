# DLens Week-0 Setup Report
Date completed: 2026-10-03
Completed with: ChatGPT free tier (guided), actions performed by Harshith

## A. Accounts
| Service | Status (DONE/SKIPPED/BLOCKED) | 2FA on? | Username / identifier (no secrets) | Notes |
|---|---|---|---|---|
| GitHub | DONE | YES | harshith769 | Repo URL: https://github.com/harshith769/DLens |
| Google AI Studio | DONE | YES (Google account) | Google account | Projects: dlens-eval (key? YES), dlens-demo (key? YES); both keys saved in password manager; Free tier; billing not enabled |
| Groq | DONE | UNKNOWN / not exposed in current free-tier UI | Groq account | Key created? YES; key saved in password manager |
| dbt Learn | DONE | n/a | dbt Learn account | Fundamentals enrolled? YES |
| Streamlit Community Cloud | DONE | via GitHub | GitHub: harshith769 | Dashboard reachable? YES |
| PyPI | DONE | YES | PyPI account | Email verified? YES |
| TestPyPI | DONE | YES | TestPyPI account | Email verified? YES |
| Hugging Face (optional) | SKIPPED | UNKNOWN | | Not required for setup |

Where keys are stored (location type only, e.g. "Bitwarden" / "private notes file outside repo"): password manager

## B. GitHub repo
- URL: https://github.com/harshith769/DLens
- Visibility: public
- Licence: Apache License 2.0
- Initial files present: LICENSE, Python .gitignore; README.md deferred

## C. Gemini free-tier limits (project dlens-eval)
| Model ID (exact) | RPM | TPM | RPD | Notes |
|---|---:|---:|---:|---|
| Flash-Lite: gemini-flash-lite-latest | 15 | 250K | 500 | Script selected this exact model ID; Rate Limit UI displayed Gemini 3.5 Flash Lite |
| Flash: UNKNOWN | UNKNOWN | UNKNOWN | UNKNOWN | Exact Flash limits were not captured |
- Free-tier data may be used by Google? UNKNOWN
- Billing enabled? (must be NO): NO

## D. Groq free-tier limits
| Model | Req/min | Req/day | Tokens/min | Tokens/day |
|---|---:|---:|---:|---:|
| openai/gpt-oss-120b | 30 | 1K | 8K | 200K |
| openai/gpt-oss-20b | 30 | 1K | 8K | 200K |
- Other free models listed: Llama models listed (including meta-llama/llama-prompt-guard-2-22m and meta-llama/llama-prompt-guard-2-86m); Qwen model listed (qwen/qwen3.8-27b)

## E. PyPI name and Trusted Publishing
- pypi.org/project/dlens-lineage → 404 (free)? Y
- Pending Trusted Publisher on PyPI: DEFERRED (values used: owner=harshith769, repo=dlens, workflow=release.yml, environment=pypi)
- Pending Trusted Publisher on TestPyPI: DEFERRED

## F. Laptop checks (WSL2)
| # | Check | Result (paste key line of output) | Pass? |
|---|---|---|---|
| B1 | nvidia-smi | GPU: NVIDIA GeForce RTX 4050 Laptop GPU / Driver: 591.66 / CUDA: 13.1 / VRAM: 6141 MiB | YES |
| B2 | free -h | total / available: 9.7 GiB / 9.1 GiB; .wslconfig changed? YES | YES |
| B3 | df -h ~ | free space: 941 GiB | YES |
| B4 | uv + Python 3.12 | uv version: 0.12.22; python: 3.12.15 | YES |
| B5 | Ollama + qwen3:8b pull | ollama version: 0.35.1 | YES; qwen3:8b downloaded; observed download size ~5.2 GB |
| B6 | qwen3:8b on GPU | ollama ps: 30%/70% CPU/GPU at context 4096; speed estimate: 16.3 tok/s; fallback qwen3:4b result: 100% GPU at context 8192; speed estimate: 61.7 tok/s | YES |
| B7 | dbt + sqlglot install | dbt-core: 1.12.5; dbt-duckdb: 1.11.0; sqlglot: 30.21.0; conflicts: NONE observed | YES |
| B8 | jaffle_shop dbt build | PASS count: 28; ERROR count: 0; error text: none | YES |
| B9 | sqlglot lineage(None) | output: dict ['b'] | YES |

## G. Recommended config values (derived only from the numbers above)
- GEMINI_MODEL=gemini-flash-lite-latest
- GEMINI_DAILY_BUDGET=400
- GROQ_DAILY_TOKENS=200000
- OLLAMA_MODEL=qwen3:4b
- DBT_CORE_VERSION=1.12.5
- DBT_DUCKDB_VERSION=1.11.0
- SQLGLOT_VERSION=30.21.0

## H. Open items and problems
- Gemini newest Flash exact model ID and limits: UNKNOWN / not captured in the final Rate Limit screenshot.
- Gemini free-tier data-use-for-improvement setting: UNKNOWN.
- Groq 2FA: UNKNOWN / no 2FA or MFA option was visible in the current free-tier account UI.
- dbt Fundamentals estimated total course length: UNKNOWN; enrollment succeeded but complete total duration was not captured.
- PyPI Trusted Publisher: DEFERRED.
- TestPyPI Trusted Publisher: DEFERRED.
- Hugging Face account: SKIPPED.
- README.md initialization in GitHub repo: DEFERRED.
- CLAUDE.md WSL placement/content: UNKNOWN; a CLAUDE.md file exists in Windows Downloads, but it was not found under WSL home and its contents were not independently verified there.

## I. Anything surprising
- WSL initially exposed 7.6 GiB RAM despite 15.7 GB physical RAM. After increasing the WSL allocation, 9.7 GiB became visible.
- qwen3:8b did not achieve full GPU placement: 30% CPU / 70% GPU at context 4096 and 36% CPU / 64% GPU at context 8192.
- qwen3:4b achieved 100% GPU placement at context 8192 and generated at 61.7 tok/s in the scripted benchmark.
- The interactive Ollama command `/set think false` produced an error; `/set nothink` successfully disabled thinking.
- Starting a second `ollama serve` failed because 127.0.0.1:11434 was already in use; the existing Ollama server was retained.
- `uv` correctly installed packages into the venv, while the shell's plain `pip` initially pointed to Conda. From now on, use `uv pip` / `uv run`.
- The dbt version constraints `dbt-core~=1.12` and `dbt-duckdb~=1.10` resolved to dbt-core 1.12.5 and dbt-duckdb 1.11.0 with no observed conflict.
- The jaffle_shop_duckdb integration test completed successfully: 28 total tasks, PASS=28, ERROR=0.
- The Gemini test call succeeded with model ID gemini-flash-lite-latest, and the Rate Limit page then exposed 15 RPM, 250K TPM, and 500 RPD.