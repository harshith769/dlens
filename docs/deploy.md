# Deploying the public demo (Streamlit Community Cloud)

The demo is the normal DLens UI in **demo mode**: it reads a prebuilt `synthetic_shop` bundle in
`demo/` (no dbt, no `target/`, no Ollama), replays 10 precomputed answers with no model call, and
sends live questions to Gemini Flash-Lite on the **separate demo AI Studio project**, behind hard
caps. How it works: `docs/explain/deploy.md` (added with v0.2.0).

## What gets deployed

| Path | Role |
|---|---|
| `demo/streamlit_app.py` | Entrypoint. Forces `DLENS_DEMO=1`, puts `src/` on `sys.path`, runs `src/dlens/ui/app.py` |
| `demo/requirements.txt` | The Cloud install. Generated from `uv.lock` by `make demo-requirements`: base + agent + ui, without dbt and groq. No torch. About 418 MB installed (mostly pyarrow, via Streamlit) |
| `demo/synthetic_shop/` | `graph.json` plus only the 21 source/seed files the graph cites (`make demo-bundle`) |
| `demo/presets/*.json` | 10 full run records made with local `qwen3:4b-instruct-2507-q4_K_M` (`scripts/record_presets.py`) |

Cloud looks for a dependency file next to the entrypoint first, so `demo/requirements.txt` wins
over the root `uv.lock` (which stays the dev lock). The CI job `demo-install` boots the entrypoint
from a venv built only from `demo/requirements.txt` and clicks a preset, and fails if the file is
out of date with `uv.lock`.

## Cloud settings

At share.streamlit.io → **Create app** → *Deploy a public app from GitHub*:

| Field | Value |
|---|---|
| Repository | `harshith769/dlens` |
| Branch | `main` |
| Main file path | `demo/streamlit_app.py` |
| App URL | your choice, e.g. `dlens-demo` (→ `https://dlens-demo.streamlit.app`) |
| Advanced settings → Python version | **3.12** (the Cloud default; it cannot be changed after deploy without redeploying) |
| Advanced settings → Secrets | the two keys below |

`DLENS_DEMO=1` needs no setting: the entrypoint forces it.

### Secrets (names only)

Paste into the Secrets box as TOML (`NAME = "value"`), with values typed there and nowhere else:

| Name | Value |
|---|---|
| `GEMINI_API_KEY` | the key of the **demo** AI Studio project (never the dev/eval key) |
| `DLENS_GEMINI_MODEL` | `gemini-3.5-flash-lite` |

- The model ID is the stable code listed on Google's models page
  (https://ai.google.dev/gemini-api/docs/models, checked 4 Oct 2026), not a `-latest` alias;
  the adapter refuses empty and `-latest` IDs. The same ID passed the dev smoke on 4 Oct 2026.
- The key is read with `st.secrets` and passed to the client; the app never prints or logs it
  (tested). To change it later: app → **Settings → Secrets**, save; the app restarts.
- Without `GEMINI_API_KEY` the app still runs: presets and Explore work, and live questions show
  "Live questions are off".
- The repo never holds a key: `**/.streamlit/secrets.toml` is gitignored and a pre-commit hook
  scans for secrets.

## The caps

| Cap | Value | Where |
|---|---|---|
| Model calls per day, whole app | 50 (`QuotaCounter`, day rolls at midnight US Pacific) | `dlens.ui.demo.DAILY_CALLS` |
| Live questions per browser session | 5 | `SESSION_QUESTIONS` |
| Question length | 300 characters | `MAX_QUESTION_CHARS` |
| Calls per question | at most 8; a question starts only if 8 still fit today | `MAX_LLM_CALLS` |

When a cap is hit the answer area shows **"Demo limit reached"** and points to the presets. A
Gemini error (busy, rate-limited) shows "The demo model is unavailable right now". Presets and
Explore lineage never call a model and never count.

**Known gap:** the 50/day counter is a SQLite file in the app container
(`~/.local/state/dlens-demo/`). Cloud's disk is not persistent: a reboot, redeploy or wake from
sleep resets it to 50. The hard backstop is the demo AI Studio project's own free-tier limit
(about 500 requests/day for Flash-Lite per project on 3 Oct 2026); that project is separate, so
the dev/eval budget is never touched.

## Check after deploy

1. The header reads **"Gemini Flash-Lite (demo) · 50 of 50 left today"** (or fewer).
2. Click a preset: it answers at once with **"Precomputed with local qwen3:4b"**, and the count
   does not change.
3. Ask one live question, e.g. *Where does stg_orders.order_date come from?*: an answer with
   citations, and the count drops by the calls used (2-8).
4. The Source tab shows the cited SQL; Explore lineage draws a graph.

## Check the limits later

- **App-wide:** the header's "x of 50 left today" is the live counter.
- **Google side:** aistudio.google.com → the demo project → *Usage* (requests per day per
  model). This is the number that matters if the container counter was reset.
- **Logs:** app → **Manage app** → logs. Run records go to `~/.local/state/dlens-demo/runs/` in
  the container (not persistent); they hold no key.

## Rehearse locally (no key needed)

```bash
uv run --extra agent --extra ui streamlit run demo/streamlit_app.py
```

Without secrets this shows presets and Explore, with live questions off. Its state lives in
`~/.local/state/dlens-demo/`, apart from the dev quota counter.

## Maintenance

- After a lineage or **version** change: `make demo-bundle`, then re-record the presets
  (`uv run --extra agent python scripts/record_presets.py`). `graph.json` stores the dlens
  version, and the app refuses a graph built by another version (tests catch this).
- After a dependency change: `make demo-requirements` (CI fails if you forget).
- Pre-deploy smokes (owner-run, dev key, dev counter): `scripts/smoke_llm.py --provider gemini`
  and `scripts/smoke_agent.py --provider gemini`, both refused without `--yes-spend-quota`.
