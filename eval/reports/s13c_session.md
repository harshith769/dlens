# S13c session report: F1 (d), F6 gate, linker items, adapters, seed

**Date:** 22 Oct 2026. **Branch:** `s13-gates-linker` from main c015798 (not merged; the owner
merges). **Design:** `docs/plans/s13c-design.md` v1.1 (decisions and the L1 correction).

## Status

| item | state |
|---|---|
| Design + STOP | 1bccff8; owner decisions recorded 7dd5dad |
| A1 openai_compat | done, 1a33e62 |
| A2 Ollama connection errors | done, 2a7e1d3 |
| L2 dotted unknown model | done, 9b4e6f3 |
| L1 qualified tier (+ drop rule, owner correction) | done, 81a1c94 |
| F6 re-measure on the new linker | same split, no flip (no STOP) |
| F1 (d1) | done, a47d7c6 |
| F6 gate | done, f68db17; A6 budget fits (no STOP) |
| S seed | done, 9abd0dc; Ollama seed 42; Gemini seed implemented, **off** |
| L3 chunker + tie-break | **DEFERRED** to after v1.0 (moved to "Later") |
| L4 dev-15, L5 "exchange rate" | no change / no rule (as approved) |
| Diagnostics | 08f7f77: post-S13c qwen dev run (seed 42) + S0-linked hybrid on (new files) |
| Agent sha | `4a643557e1a292f28823cb1dd2ee64d08cd714007f1b05bfa2df3e70b3ef0daf` (after the CI fix b5b2b7e; the diagnostic ran on `2a2d9b1e…`, see below) |
| Cloud LLM calls | **0**. The Gemini seed smoke is prepared, not run. No `.env` read |
| CI | first push (5129b37, run 39832379870) **failed**: the core install lacked httpx (A2 bug); fixed in b5b2b7e; see the run for the pushed head |

## Decisions (owner, 22 Oct 2026) and what was built

| # | item | decision | built |
|---|---|---|---|
| 1 | F1 option (d) | APPROVED (d1) + derivation-wording guard | Indirect edges bridge in R8c only if an `impact_downstream` result showed them, and never for derivation wording |
| 2 | F6 gate | APPROVED, re-measure condition | Code `search_docs` (rule `docs_evidence`) only with an index, no unknown dotted model, and ≥ 1 linker candidate |
| 3 | L1 | APPROVED + four negatives, then a **correction** | `qualified` tier, plus the drop rule (below); one existing test re-pointed, owner-approved |
| 4 | L2 | APPROVED | A dotted id with an unknown model gets no candidate and never reaches hybrid |
| 5 | L3 | DEFERRED to after v1.0 | – |
| 6 | L4 dev-15 | no change | – |
| 7 | L5 "exchange rate" | no rule | Reported: L1 / L2 do not change `lk-no_match-016` |
| 8 | A1 | APPROVED | Raise after the `except` block, sentinel test |
| 9 | A2 | APPROVED (a) | Connection errors retryable, nothing chained |
| 10 | Seed | APPROVED: Ollama 42 (S1 + S4); Gemini off | `seed` in Ollama options and params; `DLENS_GEMINI_SEED` opt-in; manifest records it |

**L1 correction (owner, mid-session; written after seeing dev, stated as such).** The design
said the qualified tier alone makes dev-75 pick `raw_customers.last_name`. It did not: the seed
layer prior (−0.005) kept the tie with `stg_customers.last_name`. The owner approved the **drop
rule**: when a qualified candidate exists for a mention, other models' stage-2 readings of that
mention are dropped.

## Measurements before code (offline unless marked)

- **F1 (d1):** 37 / 55 gold-consistent R8 drops complete on both pilot records, 0 / 3
  inconsistent, 0 trace-family claims.
- **F6 gate, re-measured on the L1 / L2 linker before any F6 code:** the same split.
  - The step runs for dev-66, 78, 82, 84, 86.
  - dev-41, 87, 93, 94, 95, 96 stay refused.
  - A6 budget: largest added chunk evidence 649 est. tokens; largest answer prompt 1,401 against
    2,722 (no trim).
- **Linker sets** (`scripts/s13c_measure.py --part linkerset / linkerdiff`; the committed S08
  report is not regenerated):

| change | set | hybrid | top-1 | ambiguous |
|---|---|---|---|---|
| L2 | linker-dev | off / on | 85 / 88, unchanged | unchanged |
| L2 | dev mentions | on | no-match 8 → 9 (dev-93) | 19 → 18 |
| L1 | linker-dev | off | 85 → 87 / 104 | 37 → 33 |
| L1 | linker-dev | on | 88 → 91 / 104 | 50 → 44 |
| L1 | dev mentions | off / on | 77 → 79, 78 → 83 / 87 | 8 → 4, 18 → 11 |

- linker-dev cases changed by L1 (all to the gold top-1): lk-model_qualified-007, 011, 013, 014,
  016, 017.
- **linker-test (reported only, never used to choose):**
  - L2 changes nothing.
  - L1: top-1 89 → 90 (off), 95 → 96 (on); ambiguous 20 → 17, 32 → 29; changed cases
    lk-model_qualified-004, 010, 012.
  - `lk-no_match-016` ("exchange rate") is unchanged by L1 and L2.
- **Seed (local Ollama, owner protocol):**
  - Setup: identical saved prompts, 5 sends each, one request at a time,
    `OLLAMA_NUM_PARALLEL` 1, the model resident.
  - Result: seed null, 4 / 12 prompts gave 2 outputs; seed 42, 0 / 12.

## Commits

| commit | what |
|---|---|
| 1bccff8 | design v0.1 + `scripts/s13c_measure.py` |
| 7dd5dad | owner decisions recorded |
| 1a33e62 | A1 |
| 2a7e1d3 | A2 |
| 9b4e6f3 | L2 (+ linker-set measurement parts) |
| 81a1c94 | L1 + drop rule, design v1.1 correction |
| a47d7c6 | F1 (d1) |
| f68db17 | F6 gate (+ budget measurement part) |
| 9abd0dc | seed; Gemini seed opt-in; owner smoke script |
| 08f7f77 | diagnostics (runs + report) |
| 5129b37 | this report (first version) |
| b5b2b7e | **bug fix:** `ollama.py` imports httpx lazily (CI core install has no httpx) |
| this commit | report update |

## Tests

**Added** (record fixtures read the committed pilot records; no live model):

| file | covers |
|---|---|
| `tests/unit/agent/test_openai_compat_chain.py` | A1: transport errors and a 401 hold no key in any text form, `__cause__` or `__context__` (3 of 4 fail on the old code) |
| `tests/unit/agent/test_ollama_connection.py` | A2: ConnectionError / RemoteProtocolError / ReadTimeout retryable; a server error keeps its status; nothing chained |
| `tests/unit/agent/tools/test_entity_s13c.py` | L2: unknown dotted model → no candidate, hybrid never reached (a stub index that fails if searched). L1: dev-29 / 40 / 56 / 71 / 75 and the leaderboard phrase unique `qualified` top-1. The owner's negatives (dev-15, multi-model, "orders in the last month", "order_id in orders", wrong model; nothing dropped when not qualified). The drop is per mention |
| `tests/unit/agent/validator/test_indirect_completion.py` | F1: dev-53 (qwen) and dev-71 (Gemini) pass (both fail on the old validator); derivation and "aggregated" wording, a non-impact-shown JOIN edge, "directly" and the dev-65 siblings still fail |
| `tests/unit/agent/loop/test_docs_gate.py` | F6: CI plumbing with a real fixture index (fake embedder; the linker decision stubbed to the measured outcome): the 5 run, the 6 blocked, no index, a lineage question with evidence. Local-only: the real decision on all 11 with the bge index (skipped without a local index) |
| `tests/unit/agent/test_seed.py` | Seed: Ollama sends 42; the cache key moves; `make_client` gives the same params to S1 and S4; Gemini off by default and on when set; the manifest records it |
| `tests/unit/test_smoke_gemini_seed.py` | The owner smoke refuses without `--allow-cloud` or the pinned env |

**Existing tests edited (before → after):**
- `tests/unit/eval/test_s4.py`: `CURRENT_AGENT_SHA` updated in each agent-code commit (A2 rule)
  → `2a2d9b1e…cd88`.
- `tests/unit/agent/tools/test_entity_v2.py::test_cap_is_on_the_printed_score_only`
  (**owner-approved re-point**): the text "sales tax in fct_orders" → "sales tax on fct_orders".
  Assertions unchanged (printed 0.94; `fct_orders.sales_tax` raw 0.940 > the other model's
  0.895). Reason: "in" now makes a qualified mention, which drops the other candidate.
- `tests/unit/agent/test_ollama.py::test_params_sent` (the approved seed): `options`
  `{"temperature": 0, "num_ctx": 8192}` → `{…, "seed": 42}`.
- `tests/unit/eval/test_manifest.py::test_model_identity_records_digest_version_and_sampling`
  (the approved seed): Ollama `sampling.seed` `None` → `42`. The "other provider" assert
  (`seed is None`) is unchanged.

**Guards:** every other existing test passes unchanged. That includes the B3 validator outcome
snapshot, R7, the "directly" and sibling R8c tests, R4, the A2 raw-view pin, the F2–F5 tests of
S13b and the existing linker v2 tests.

Final local run: `make lint` clean; `make test` 1,683 passed, 19 skipped.

## Frozen checks

- `git diff --stat c015798 -- ':(glob)eval/runs/s4/*.jsonl' ':(glob)eval/runs/s4/*.json'
  ':(glob)eval/runs/s0/*' eval/runs/s1 eval/reports/s13 eval/reports/s13b eval/scores
  eval/metrics.py eval/questions`: **empty**.
- `src/dlens/lineage` and `src/dlens/retrieval`: no diff. L3 is deferred, so the chunker is
  untouched.
- New run files only:
  - `eval/runs/s4/diagnostic/s13c-qwen3-…-dev.*`;
  - `eval/runs/s0/diagnostic/s13c/s0-linked-hybrid-dev.*`.
- `s1.frozen_hashes() == FROZEN` (the three `test_s1.py` asserts pass). The seed is recorded in
  the S1 design change log (no B8 component changed).
- **`scripts/check_s0_stable.py` now reports 4 S0-linked (hybrid-off) records differing** from
  the committed `eval/runs/s0/s0-linked-dev.jsonl`: dev-48, 55, 71, 75.
  - These are exactly L1's hybrid-off dev-mention changes, an approved linker change, not
    instability.
  - The committed records are not rewritten. Whether to refresh the committed S0 baseline or
    teach the check about intended changes is an owner decision (carry-forward).
- No absolute path or username in a committed file (grep). No cloud call. No
  `--allow-cloud`.

## Diagnostic summary (post-S13c dev diagnostic; not a result)

`eval/reports/s13c/diagnostic_dev.md`: qwen, local, agent `2a2d9b1e`, seed 42, 0 cache hits, 324
calls.

| validated view | pilot | post-S13b | post-S13c |
|---|---|---|---|
| node-set F1 | 0.561 | 0.578 | 0.607 [0.52, 0.70] |
| trace F1 · impact F1 | 0.581 · 0.524 | 0.607 · 0.524 | 0.637 · 0.552 |
| false refusal | 0.149 | 0.126 | 0.080 |
| refusal accuracy | 1.000 | 1.000 | 1.000 |
| hallucination rate | 0.000 | 0.000 | 0.000 (77) |
| citation valid (answer) | 0.899 (69) | 0.901 (71) | 0.885 (78) |
| Ask refusals | 5 / 12 | 5 / 12 | 2 / 12 |

- **Attribution (record-visible):**
  - F6 `+docs_evidence` on dev-66, 78, 82, 84, 86. dev-82 then refused itself (a model refusal).
  - F1 indirect completions on dev-53, 65, 71.
  - L1 / L2 linker marks on 12 questions; dev-29, 40, 71 moved.
- **Nothing moved the wrong way** per question.
- **Citation validity:** the aggregate dip comes only from newly answered questions. dev-84 and
  dev-86, F6 docs-based Ask answers, score 0.0 under M7. No previously answered question changed.
- **S0-linked hybrid on (no LLM):** node-set F1 0.809 → 0.882; refusal accuracy 0.889 → 1.000
  (dev-93 refused); dev-29, 40, 55, 56, 71 answer instead of asking for clarification.

## For the owner

- **Gemini seed smoke (not run; it spends 1 call):**

  ```
  DLENS_PROVIDER=gemini DLENS_GEMINI_MODEL=gemini-3.5-flash-lite DLENS_GEMINI_SEED=42 \
    GEMINI_DAILY_BUDGET=475 uv run --extra agent python scripts/smoke_gemini_seed.py --allow-cloud
  ```

  It prints only `OK (HTTP 200)`, `ProviderError (HTTP <status>)` or an exception class.
  - If it succeeds: turning the Gemini seed on by default is one commit with a test.
  - If it fails: the seed stays off, and that is recorded.
- **Explain gate:** new "changed in S13c" sections, each with explain-back questions, in
  `docs/explain/llm.md` (A1, A2, S), `linker.md` (L1, L2), `validator.md` (F1) and `agent.md`
  (F6).

## CI failure and fix

The first push (5129b37, CI run 39832379870) failed on the 4 jobs that run the core install: both
`lint-test` jobs (the core step) and both `core-artifacts` jobs.
- **Cause:** A2 added a top-level `import httpx` to `src/dlens/agent/llm/ollama.py`. The CLI
  imports that module (`cli → loop → strip_think`), and the core install has no httpx (it comes
  with the agent extra), so `dlens` could not start. Locally every extra was installed, so
  `make test` passed.
- **Fix (b5b2b7e, its own commit):** httpx's `TransportError` is looked up only where it is
  caught. Without httpx, only `ConnectionError` is mapped, and no httpx error can occur then.
  Behaviour with the agent extra is unchanged.
- **Checked:** an import blocker for httpx, ollama, google.genai, bm25s, onnxruntime and
  streamlit, and `import dlens.cli` succeeds.
- **The diagnostic run** (agent `2a2d9b1e…`) predates the fix. The fix changes only where httpx
  is imported, so with the agent extra installed (the run's environment) the behaviour is
  identical. The run is not repeated.

## Carry-forward

- **Later (deferred, full design and measurements in s13c-design.md L3):** citation-helper rules
  into the chunker, and rank tie-breaking independent of chunk ids (235 / 506 chunk ids would
  move). After v1.0.
- **Gemini seed:** pending the owner smoke above.
- **`check_s0_stable.py`:** owner decision on the 4 intended S0-linked (hybrid-off) differences
  from L1 (refresh the committed S0 baseline under a recorded reason, or let the check accept a
  listed set).
- **F6 citation validity:** the docs-based Ask answers dev-84 / dev-86 score 0.0 on M7 citation
  validity. Recorded only; the honest check is test after the 7 Dec freeze.
- Roadmap unchanged: S14, S15, Buffer A, S06c, the owner explain gate, the research re-check, and
  the v0.3 tag checks.
