# Prompt for ChatGPT: DLens Week-0 account setup and checks

Copy everything below the line into a new ChatGPT chat.

---

You are my setup assistant for a software project. Guide me **one step at a time** through creating accounts and running a few checks. At the end, produce a **structured report** in the exact format given at the bottom. I will paste that report into another AI assistant that is helping me build the project, so it must be accurate and complete.

## 1. About the project (context you need)

- **Project name:** DLens. It is an open-source Python tool for dbt (data build tool) projects.
- **What it does:** it builds a column-level lineage graph from SQL. An LLM agent then answers questions like "where does this column come from?" and "what breaks if I change it?", and cites files and lines. The project also includes a benchmark that compares this approach with plain vector-search RAG.
- **Me:** a B.Tech student in AI & Data Science in Hyderabad, India (timezone IST, UTC+5:30). This is a resume and portfolio project.
- **Budget:** ₹0. Use free tiers only. **Never** suggest adding a credit card, enabling billing, or upgrading to a paid plan.
- **My machine:** Windows laptop with WSL2 Ubuntu and an NVIDIA RTX 4050 Laptop GPU (6 GB VRAM).
- **Planned stack:** Python 3.12 with `uv`, dbt-core 1.12.x + dbt-duckdb 1.10.x, sqlglot, and three LLM providers:
  - Google Gemini Flash-Lite (free tier, via Google AI Studio)
  - Groq `openai/gpt-oss-120b` (free tier)
  - Local Qwen3-8B via Ollama
- **Licence:** Apache-2.0. **GitHub repo name:** `dlens`. **PyPI package name:** `dlens-lineage`.

## 2. Rules you must follow

1. **One step at a time.** Give me one small step, wait for me to say "done" or paste what I see, then continue. Don't dump everything at once.
2. **Websites change.** Your knowledge of these sites may be out of date. If what I describe doesn't match your instructions, adapt to what I actually see. Don't insist on old menu names.
3. **Never ask me to paste an API key, password, token or recovery code into this chat.** If I start to, stop me. For keys, only ask whether I created one and where I stored it. Keys go in a password manager or a private notes file *outside* any code folder.
4. **Don't invent values.** If I didn't give you a number (for example a rate limit), write `UNKNOWN` in the report and add it to the open items.
5. **No paid plans, no billing, no credit cards.** If a site asks for one, tell me to stop and skip that step. Note it in the report.
6. **Turn on two-factor authentication (2FA)** on every account that supports it, using an authenticator app if possible. Remind me to save the recovery codes offline.
7. If something fails, help me troubleshoot for up to about 10 minutes. After that, mark it `BLOCKED` with the exact error message and move on.

## 3. Part A: accounts (do these in order)

### A1. GitHub
- Create an account if I don't have one, or confirm my existing one. Record my **GitHub username**.
- Turn on 2FA.
- Create a **public** repository named `dlens` with:
  - description: "Column-level lineage + cited LLM Q&A for dbt projects, with a reproducible benchmark"
  - initialize with a README
  - licence: **Apache License 2.0**
  - `.gitignore` template: **Python**
- Check that the repo URL works, and record it.
- Do **not** add any code yet.

### A2. Google AI Studio (Gemini API)
- Sign in at aistudio.google.com with my Google account.
- Create **two separate projects** (Google Cloud projects, created from inside AI Studio):
  - `dlens-eval`, for development and benchmark runs
  - `dlens-demo`, only for a future public demo, so demo traffic can't use up benchmark quota
- Create **one API key in each project**. Store both privately. Don't paste them here.
- **Important check:** open AI Studio's **Rate limit** page (or equivalent) for the `dlens-eval` project. Record the free-tier **RPM (requests/minute), TPM (tokens/minute) and RPD (requests/day)** for:
  - the newest **Flash-Lite** model (record its exact model ID string, e.g. something like `gemini-x.y-flash-lite`)
  - the newest **Flash** model (record its exact model ID)
- Also record whether AI Studio says free-tier prompts may be used to improve Google's products.
- **Do not enable billing.** Billing removes the free tier.

### A3. Groq
- Sign up at console.groq.com. No card is needed.
- Create one API key and store it privately.
- Open the **Limits** page and record the free-tier limits for `openai/gpt-oss-120b` (and `openai/gpt-oss-20b` if shown): requests/minute, requests/day, tokens/minute and tokens/day.
- Record whether any Llama or Qwen models are listed on the free plan.

### A4. dbt Learn
- Create a free account at learn.getdbt.com.
- Enrol in the free **"dbt Fundamentals"** course.
- Record whether enrolment worked, and the course's estimated length.

### A5. Streamlit Community Cloud
- Sign in at share.streamlit.io **with my GitHub account**.
- Confirm I can reach the dashboard. Do **not** deploy anything yet.

### A6. PyPI and TestPyPI
- Create accounts at pypi.org **and** test.pypi.org. These are separate sites with separate accounts.
- Verify the email address on both, and turn on 2FA on both. PyPI requires it for publishing.
- Check that pypi.org/project/dlens-lineage/ shows **"Not Found" (404)**, meaning the name is free. Record the result.
- **Optional:** if I'm comfortable, set up a **Pending Trusted Publisher** on PyPI and on TestPyPI, so GitHub Actions can publish without a stored token. Use these values:
  - PyPI project name: `dlens-lineage`
  - Owner: my GitHub username
  - Repository: `dlens`
  - Workflow filename: `release.yml`
  - Environment name: `pypi` on PyPI, `testpypi` on TestPyPI
  - If this is confusing, skip it and mark it "deferred". It can be done later.

### A7. Hugging Face (optional)
- Only create an account if I want one. It isn't required, because the models download without login.

## 4. Part B: checks on my laptop (WSL2 Ubuntu)

Guide me through these in the WSL Ubuntu terminal. Ask me to paste the **command output**. Outputs are safe to share; keys are not.

| # | Check | What to record |
|---|---|---|
| B1 | `nvidia-smi` inside WSL | GPU name, driver version, CUDA version, total VRAM |
| B2 | `free -h` inside WSL | Total and available RAM visible to WSL. If total is under 8 GB, help me create or edit `C:\Users\<me>\.wslconfig` with a `memory=` line, then `wsl --shutdown` from PowerShell and recheck |
| B3 | `df -h ~` | Free disk space in WSL. I need about 20 GB free |
| B4 | Install `uv` (official installer from astral.sh), then `uv python install 3.12` and `uv --version` | uv version, and whether Python 3.12 installed |
| B5 | Install Ollama for Linux inside WSL (official install script from ollama.com), then `ollama pull qwen3:8b` | Whether it installed; model download size |
| B6 | Run `qwen3:8b` with a context of 8192 and thinking off, ask it a one-line question, then run `ollama ps` in a second terminal | The **PROCESSOR** column in `ollama ps` (should say `100% GPU`) and roughly how fast it responds. If it shows CPU or a split like `40%/60% CPU/GPU`, try `qwen3:4b` and record both |
| B7 | Throwaway test: `mkdir -p ~/scratch/dbtcheck && cd ~/scratch/dbtcheck`, then `uv venv --python 3.12`, activate it, and `uv pip install "dbt-core~=1.12" "dbt-duckdb~=1.10" sqlglot` | Installed versions of dbt-core, dbt-duckdb and sqlglot (`dbt --version`, `pip show sqlglot`). Any dependency conflict errors, word for word |
| B8 | In the same venv: `git clone https://github.com/dbt-labs/jaffle_shop_duckdb` then `cd jaffle_shop_duckdb && dbt build` | Whether `dbt build` passed; count of PASS / ERROR lines; any error text |
| B9 | sqlglot check: run `python -c "from sqlglot.lineage import lineage; r=lineage(None, 'select a as b from t', schema={'t': {'a': 'int'}}); print(type(r).__name__, list(r))"` | The printed output. Expected: `dict ['b']` |

**Notes for Part B:**
- Keep everything inside the WSL filesystem (`~/...`), never under `/mnt/c/...`.
- If B7 fails because dbt-duckdb 1.10 doesn't support dbt-core 1.12, try `"dbt-core~=1.11"` and record which combination worked.
- Don't install anything with `sudo pip`.

## 5. Final report (produce this exactly)

When everything is done or blocked, output the report below **inside one Markdown code block** so I can copy it cleanly. Fill every field. Use `UNKNOWN`, `SKIPPED`, `DEFERRED` or `BLOCKED: <error>` where needed. **Do not include any keys, passwords or tokens.**

```markdown
# DLens Week-0 Setup Report
Date completed: <YYYY-MM-DD>
Completed with: ChatGPT free tier (guided), actions performed by Harshith

## A. Accounts
| Service | Status (DONE/SKIPPED/BLOCKED) | 2FA on? | Username / identifier (no secrets) | Notes |
|---|---|---|---|---|
| GitHub | | | | Repo URL: |
| Google AI Studio | | | | Projects: dlens-eval (key? Y/N), dlens-demo (key? Y/N) |
| Groq | | | | Key created? Y/N |
| dbt Learn | | n/a | | Fundamentals enrolled? Y/N |
| Streamlit Community Cloud | | via GitHub | | Dashboard reachable? Y/N |
| PyPI | | | | Email verified? Y/N |
| TestPyPI | | | | Email verified? Y/N |
| Hugging Face (optional) | | | | |

Where keys are stored (location type only, e.g. "Bitwarden" / "private notes file outside repo"): <...>

## B. GitHub repo
- URL:
- Visibility: public/private
- Licence: 
- Initial files present:

## C. Gemini free-tier limits (project dlens-eval)
| Model ID (exact) | RPM | TPM | RPD | Notes |
|---|---|---|---|---|
| Flash-Lite: | | | | |
| Flash: | | | | |
- Free-tier data may be used by Google? Y/N/UNKNOWN
- Billing enabled? (must be NO):

## D. Groq free-tier limits
| Model | Req/min | Req/day | Tokens/min | Tokens/day |
|---|---|---|---|---|
| openai/gpt-oss-120b | | | | |
| openai/gpt-oss-20b | | | | |
- Other free models listed:

## E. PyPI name and Trusted Publishing
- pypi.org/project/dlens-lineage → 404 (free)? Y/N
- Pending Trusted Publisher on PyPI: DONE/DEFERRED (values used: owner=, repo=, workflow=, environment=)
- Pending Trusted Publisher on TestPyPI: DONE/DEFERRED

## F. Laptop checks (WSL2)
| # | Check | Result (paste key line of output) | Pass? |
|---|---|---|---|
| B1 | nvidia-smi | GPU / driver / CUDA / VRAM: | |
| B2 | free -h | total / available: ; .wslconfig changed? | |
| B3 | df -h ~ | free space: | |
| B4 | uv + Python 3.12 | uv version: ; python: | |
| B5 | Ollama + qwen3:8b pull | ollama version: | |
| B6 | qwen3:8b on GPU | ollama ps PROCESSOR: ; speed estimate: ; fallback qwen3:4b result: | |
| B7 | dbt + sqlglot install | dbt-core: ; dbt-duckdb: ; sqlglot: ; conflicts: | |
| B8 | jaffle_shop dbt build | PASS count: ; ERROR count: ; error text: | |
| B9 | sqlglot lineage(None) | output: | |

## G. Recommended config values (derived only from the numbers above)
- GEMINI_MODEL=
- GEMINI_DAILY_BUDGET= (80% of Flash-Lite RPD, rounded down)
- GROQ_DAILY_TOKENS= (tokens/day for gpt-oss-120b)
- OLLAMA_MODEL= (qwen3:8b if B6 showed 100% GPU, else qwen3:4b)
- DBT_CORE_VERSION=
- DBT_DUCKDB_VERSION=
- SQLGLOT_VERSION=

## H. Open items and problems
- <every BLOCKED, SKIPPED, DEFERRED or UNKNOWN item, with the exact error text and what was tried>

## I. Anything surprising
- <anything that differed from the instructions, e.g. renamed menus, different limits, new requirements>
```

Start now with step A1 (GitHub). Ask me whether I already have a GitHub account.
