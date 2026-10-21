# Pilot design (S13, v0.3 done-when 5, D4)

**Version:** 0.3 (21 Oct 2026). **Status:** records and sampling decided by the owner before any
pilot run (§1, §2); cloud plan confirmed by the owner with B = 475 (§3).
**Inputs:** `docs/plans/v0.3-plan.md` (done-when 5, D4, quota budget); `docs/plans/metrics-design.md`
v1.2 (M11, M13, M14, M15, M16); `docs/plans/s12-design.md` v1.3 (S4 pilot freeze);
`docs/plans/s1-design.md` (B8 freeze); `eval/reports/s12b_session.md`.

Rules that hold throughout:
- **Claude Code makes no cloud call** and never passes `--allow-cloud`. The owner runs every
  Gemini command, after confirming the quota plan.
- **S4 pilot freeze** (s12-design) holds until the pilot table is committed: S4 changes only for a
  recorded crash-class bug, and only after the owner approves.
- **S1 frozen** (B8): `s1.frozen_hashes() == FROZEN` at every commit. The linker is frozen.
  `eval/metrics.py` stays at 1.3.0 (metrics-design v1.2).
- `eval/questions/test.jsonl`, `external.jsonl` and their `.sha256` files are not touched.
- Only the synthetic corpus (`corpora/synthetic_shop`) is sent to the free cloud API.

---

## 1. Pilot records (decided 21 Oct 2026, before any result)

| panel | row | records | how |
|---|---|---|---|
| qwen3:4b (local) | S0-gold | `eval/runs/s0/s0-gold-dev.*` | committed, no LLM |
| qwen3:4b (local) | S0-linked (hybrid on) | `eval/runs/s0/s0-linked-hybrid-dev.*` | committed, no LLM; same linker flag as S4 (M14) |
| qwen3:4b (local) | S1 | `eval/runs/s1/pilot/s1-qwen3-4b-instruct-2507-q4-k-m-dev.*` | **fresh uncached local re-run** of frozen S1 v2, new empty cache `eval/cache/s1-pilot-qwen` |
| qwen3:4b (local) | S4 raw / validated / augmented | `eval/runs/s4/s4-qwen3-4b-instruct-2507-q4-k-m-dev.*` | **the S12b run, reused**: its manifest's `agent_code_sha256` must equal main's |
| Gemini Flash-Lite | S0-gold, S0-linked (hybrid on) | as above | S0 has no LLM, so it is the same in both panels |
| Gemini Flash-Lite | S1 | `eval/runs/s1/pilot/s1-gemini-…-dev.*` | new uncached run, owner-run |
| Gemini Flash-Lite | S4 raw / validated / augmented | `eval/runs/s4/s4-gemini-…-dev.*` | new uncached run, owner-run |

**Reuse check (21 Oct 2026).** The S12b S4 manifest records `agent_code_sha256`
`a6fb5b2e49fe9a104c3828c402d186196601c50c4ea25dadef0dbc982952b424` (git c007759).
`s4.agent_code_sha256()` on main 7153bff gives the same value, and `git diff c007759 7153bff --
src/dlens/agent eval/systems` is empty. The qwen S4 run is reused.

The S1 v2 files (`eval/runs/s1/s1-qwen3-…-dev.*`, `eval/runs/s1/v1/`) are never overwritten. The
pilot S1 runs write under `eval/runs/s1/pilot/`.

## 2. Sampling (decided 21 Oct 2026, before any run)

| model | temperature | thinking | seed |
|---|---|---|---|
| qwen3:4b-instruct-2507-q4_K_M (Ollama) | 0 | off (`think=False`) | none |
| Gemini Flash-Lite | **1.0** (the configured provider default, Google's advice for Gemini 3) | **model default** (`DLENS_GEMINI_THINKING` unset) | none |

- The manifest records the thinking setting actually sent to the API, not the word "default".
- Gemini records are reproducible from the cache, not deterministic. A single run at temperature
  1.0 carries more run-to-run noise than qwen at temperature 0. What is recorded for qwen:
  - **Same prompts, temperature 0:** S13's uncached S1 re-run reproduced all 96 S1 v2 raw drafts
    byte for byte, so the difference was 0.
  - **A prompt-header change only:** S11's S1 v1 → v2 re-run (same shown chunks, only the
    citation ranges in the evidence headers changed) moved composite F1 by up to ±0.045: trace
    0.303 → 0.270, impact 0.148 → 0.193, node-set 0.248 → 0.243
    (`eval/reports/s11_session.md`, "Re-run" table).
  - That ±0.04 is prompt sensitivity, not sampling noise. Temperature-1.0 noise is unmeasured.
- **S1 vs S4 is compared within each panel only.** The panels differ in model and temperature, so
  no cross-panel difference is reported as a system effect. The pilot table states the
  temperature difference.

## 3. Cloud plan (v0.3, confirmed by the owner 21 Oct 2026; the owner runs every command)

**Model.** The Gemini adapter has no built-in model id: it reads `DLENS_GEMINI_MODEL` and refuses
an empty or `-latest` value (`src/dlens/agent/llm/gemini.py`). Every command below sets
`DLENS_GEMINI_MODEL=gemini-3.5-flash-lite` (spec §15.2, `docs/deploy.md`), so the run does not
depend on what is in the owner's environment. The manifest records the id, the temperature (1.0)
and the thinking setting as sent. `DLENS_GEMINI_THINKING` stays **unset**, so the request carries
no `thinkingConfig` and the manifest records it as not sent (owner, 21 Oct 2026; §2).

**Key.** The adapter reads the dev AI Studio key from the environment variable `GEMINI_API_KEY`
(the name only; the value never appears in the repo, in a command or in a chat). Nothing loads
`.env`: the owner exports it in the shell that runs the commands.

**Limits read by the owner** (AI Studio, project `dlens-eval`, free tier, Gemini 3.5 Flash Lite,
21 Oct 2026): **RPM 15, TPM 250K, RPD 500.**

**Expected calls.**

| system | expected | worst case | basis |
|---|---|---|---|
| S1 | 96 | 192 | one answer call per question; at most one JSON repair each |
| S4 | **≈ 319** | 768 | 3.32 calls/question × 96 from the **qwen** S12b run: an **estimate**, since Gemini's regenerates and tool turns may differ; 8-call cap × 96 |
| total | ≈ 415 | 960 | |

**Daily budget and stop rule.**
- **B = floor(0.95 × 500) = 475**, enforced through `GEMINI_DAILY_BUDGET=475` in every command
  (the code default 400 is not the 95% rule).
- `QuotaCounter` is one SQLite file per state dir, keyed by (provider, calendar day in
  America/Los_Angeles).
  - It reserves a call atomically **before** sending it. Failed calls count, cache hits do not.
  - Every process using the dev state dir shares the count, so **S1 and S4 on one day stop at
    475 together**, not at 475 each.
- When the count reaches 475, the next call raises `QuotaExceeded`. The runner stops cleanly and
  writes the records so far plus a manifest (`quota.daily_budget`, `quota.used_today`,
  `quota.day_key`).
- **The local counter sees only this machine's calls.** Google's RPD counts every use of
  `dlens-eval` that day, from any machine or key. The owner confirms nothing else uses the project
  (21 Oct 2026). If something did, Google could return 429 before the local counter reaches 475
  (see "On a 429" below).
- **RPM.** The limiter's rate is a **code constant**, `RPM_LIMITS["gemini"] = 15`
  (`src/dlens/agent/llm/ratelimit.py`). There is no env setting for gemini:
  `DLENS_OPENAI_RPM` applies to the openai preset only. It stays at 15, which equals Google's
  limit, with no code change. The limiter keeps a sliding 60 s window on the client's clock, so
  this client never sends a 16th call within 60 s. Google's window may not line up with it, so
  an occasional 429 at the edge is possible.
- **TPM** is not binding: every call is capped at ~3K input tokens, so 15 calls/min is about 45K
  tokens/min, against a 250K limit.
- At 15 RPM, S1 (≈ 96 calls) takes at least ~7 min and S4 (≈ 319) at least ~22 min.
- Leave `DLENS_STATE_DIR` unset (the dev counter), never the demo project's state dir.

**On a 429 / RESOURCE_EXHAUSTED** (from code: `gemini.py` `RETRYABLE` has 429; `s1.py` `_llm`;
`loop.py` `Agent._llm`):
- The adapter raises `ProviderError(retryable=True)`. Both runners **retry once**, and that retry
  is a second reserved call, so **both attempts count** on the local counter. The retry first
  waits for a free slot in the limiter's window.
- If the retry also fails, that question ends as a refusal whose `error` starts with
  `ProviderError: gemini call failed (429)`, and **the run continues** with the next question.
  Only `QuotaExceeded` stops a run. In S4 the failed attempts are recorded steps and count
  toward the question's 8-call cap.
- Failed responses are never cached, so **re-running the same command is a free replay** of every
  successful call: only the failed questions spend quota again.
- If the log shows `ProviderError … (429)` on several consecutive questions (Google's own RPD or
  a sustained limit), **stop the run (Ctrl-C) and report it**. Continuing would spend two counted
  attempts per question for nothing.

**Quota day in IST.** The Pacific day resets at **12:30 IST until 1 Nov 2026** (PDT) and at
**13:30 IST from 1 Nov 2026** (PST). Every resume message repeats this.

**Day plan.** With B = 475, **one day is expected** (≈ 415 calls): S1 first, then S4 on the same
quota day. If the budget stops a run, re-run the **same command** after the next Pacific reset.
Every call already made is replayed from that system's cache for free, so only the missing calls
spend quota. With temperature 1.0 the replay is still exact, because the cache keys on the
request. Worst case: 960 calls take 3 quota days (ceil(960 / 475) = 3).

**Complete:** the manifest's `record_count` is 96 and no record's `error` starts with
`QuotaExceeded` or `ProviderError`. Otherwise the same command is re-run after the cause clears.
A partial records file is never scored as the pilot run.

**Counter check** (read-only, no LLM call; run it before each command):

```
GEMINI_DAILY_BUDGET=475 uv run python -c "import os; from dlens.agent.llm.config import quota_path; from dlens.agent.llm.quota import QuotaCounter, default_budgets; q = QuotaCounter(quota_path(), default_budgets(os.environ)); print('gemini used today:', q.used('gemini'), 'remaining:', q.remaining('gemini'))"
```

**Exact commands** (new empty cache dir per system):

```
# 1. S1 (Gemini), records -> eval/runs/s1/pilot/s1-gemini-3-5-flash-lite-dev.*
DLENS_PROVIDER=gemini DLENS_GEMINI_MODEL=gemini-3.5-flash-lite GEMINI_DAILY_BUDGET=475 \
  DLENS_CACHE_DIR=eval/cache/s1-pilot-gemini \
  uv run --extra agent --extra retrieval python eval/systems/s1.py --out eval/runs/s1/pilot --allow-cloud

# 2. S4 (Gemini), records -> eval/runs/s4/s4-gemini-3-5-flash-lite-dev.*
DLENS_PROVIDER=gemini DLENS_GEMINI_MODEL=gemini-3.5-flash-lite GEMINI_DAILY_BUDGET=475 \
  DLENS_CACHE_DIR=eval/cache/s4-pilot-gemini \
  uv run --extra agent --extra retrieval python eval/systems/s4.py --allow-cloud
```

- The cache dirs are gitignored. **Keep them** until the pilot table is committed: they are what
  makes a resume free and the records reproducible.
- **Data sent (rule 6):** free-tier inputs may be used by Google. Only the synthetic corpus
  (`corpora/synthetic_shop`: its SQL, YAML and docs, plus the dev questions) is sent. No other
  code or data is sent.

### 3.1 Run log (Gemini)

- **S1, quota day 21 Oct 2026 (PT):** complete in one pass. 96/96 records, 96 calls, 0 cached,
  0 errors. Committed in 8ae3284.
- **S4, quota day 21 Oct 2026 (PT): partial, not committed.**
  - First attempt: the run crashed at dev-38 with `httpx.RemoteProtocolError` ("Server
    disconnected without sending a response"), after the SDK's own retry gave up.
  - Resume (same command): dev-01–37 replayed from the cache (hits), dev-38 was partly cached,
    then fresh calls ran until `QuotaExceeded` at dev-82. 82 records were written, and dev-82
    carries the `QuotaExceeded` error. This used up the 475 budget for the day.
  - The partial file is not committed. The owner re-runs the same command after the next reset
    (12:30 IST on 22 Oct 2026). That run rewrites the full file, and the result is committed
    only when it meets "Complete" (above).
- **Crash-class gap (recorded, not fixed now; owner decision, 21 Oct 2026):** the Gemini adapter
  does not map transport errors (`httpx.RemoteProtocolError` and other connection drops) to a
  retryable `ProviderError`. The error escapes the runner's retry-once path and stops the run
  instead of becoming one failed record. It is not fixed during the pilot: a resume from the
  cache is cheap, and an adapter fix would change the agent-code sha (pilot freeze). Revisit if
  it recurs. The session report records this as well.
- **Latency (M15):** the S4 Gemini latency figures use **uncached questions only, with n
  shown**. Questions replayed from the cache on a resume are excluded, because their latency is
  not a provider latency.

## 4. Post-pilot fix candidates (dev-found; verified on test only after the 7 Dec freeze)

Source: `eval/reports/s13/prep_audit.md` (S12b S4 qwen dev run). **No code change now** (pilot
freeze). Each fix is checked on dev for regressions, then measured on test only after the 7 Dec
freeze.

**Caveat:** "consistent" means every dotted mention of the claim is in the question's gold node
set for its primary mode. It does **not** mean the relation the claim states was verified.

| id | fix | rule this follows | audit numbers it rests on |
|---|---|---|---|
| F1 | **R8:** accept a claim that cites one edge of a multi-hop path when the ledger connects its columns (the path is in this question's tool results) | Code guarantees, the LLM narrates: if the ledger proves the link, the claim is supported, and citing every hop is a completeness matter, not a truth matter | R8 dropped 11 claims, 10 of them gold-consistent: dev-53 ×4, dev-65 ×4, dev-72 ×2. Headline F1 raw → validated: dev-53 0.149 → 0.032, dev-65 0.903 → 0.741 |
| F2 | **R4:** resolve SQL table / CTE aliases in claim text before the hallucination check. Use the same guard as M7 (iv-k+) (`metrics.relation_names`: CTE and derived-table names) and extend it to ref aliases (`{{ ref('fct_orders') }} as orders`), which `relation_names` does not cover today | Symmetry (rule 12): validator and metric treat the same token the same way. Today M3's identifier filter ignores `orders.order_date` and R4 calls it hallucinated | R4.hallucinated dropped 6 claims, 3 consistent: dev-30 (`orders.order_date`, `shipments.shipped_at`) and dev-46 ×2 (`orders.order_date`). dev-46 ends "no verifiable claims" (clarify 1 → 0, a false refusal) |
| F3 | **Regenerate fallback:** if the regenerated draft refuses while the first draft had passing claims and/or a verdict, keep the first draft's passing claims and verdict | Salvage keeps the best verified content; a regenerate exists to fix failures, not to discard checked claims | dev-75: raw verdict `no` (correct), the regenerated draft refused with `reach_verdict: null`. yes/no 1.0 → 0.833 (n = 6), and one false refusal |
| F4 | **Target preservation:** if no kept claim names the question's target, salvage the first draft's target claim when it fails only on a repairable id (R2) | The answer must stay about the question asked; an id problem is a citation fault, not a content fault | dev-16: the target claim failed R2 (truncated `e_81a3f`), and its rewrite failed R5. Chain 1.0 → 0.5 (n = 2), upstream F1 1.0 → 0.0 |

F1–F4 change the validator rules, so each needs an approved plan that names it (CLAUDE.md).
Design options per fix, and F5 (the transport-error gap, §3.1): `docs/plans/post-pilot-fixes.md`.

## Change log

- 21 Oct 2026: v0.1. Pilot records and sampling fixed by the owner before any pilot run (§1, §2).
  qwen S4 reuse check passed (equal agent-code sha).
- 21 Oct 2026: §4 post-pilot fix candidates F1–F4 (owner, after STOP A). No code change.
- 21 Oct 2026: v0.2. §3 cloud plan: model id, call estimates, budget rule
  B = floor(0.95 × RPD) (pending), shared counter, IST reset times, day order, commands.
- 21 Oct 2026: v0.3. Owner confirmed the quota plan: AI Studio RPM 15 / TPM 250K / RPD 500,
  B = 475; RPM limiter stays at the 15 code constant; 429 behaviour from code; Google's RPD is
  project-wide; thinking unset; ±0.04 note cited (prompt sensitivity, S11) vs 0 (temperature 0, S13).
- 21 Oct 2026: §3.1 run log. S1 Gemini complete. S4 Gemini partial: a transport-error crash at
  dev-38, recorded as a crash-class gap (no fix, owner decision), then QuotaExceeded at dev-82.
  Resume after 12:30 IST on 22 Oct. Latency uses uncached questions only (M15).
