# S13b session report: post-pilot fixes F1–F6

**Date:** 22 Oct 2026. **Branch:** `s13-postpilot-fixes` from main e072c38 (not merged; the
owner merges). **Design:** `docs/plans/post-pilot-fixes.md`. **ADR:** 0029 (spec §0 row 37).

## Status

| item | state |
|---|---|
| Step 0 diagnosis (read-only) | done, fc97c35; ledger rebuild fidelity qwen 77 / 77, Gemini 88 / 88 |
| STOP 1 decisions | F2 (a), F3 (a), F4 (a), F5 (a) + A4 sub-item approved; F1, F6 deferred |
| Fixes | F5 59d22b3 → F4 9cdb11b → F3 03c8837 → F2 bac08bd (F1, F6: no code) |
| New agent sha | `77e25642205637bb458f3dc66703ffa75a57d68b4a1861bd08aa9e3b20ceb6d7` |
| Pilot records' sha | `a6fb5b2e…b424`, unchanged, not rewritten |
| Diagnostic dev re-run | done once, 0f069d1; labelled "post-fix dev diagnostic", not a result |
| Cloud LLM calls | **0** (no `--allow-cloud`, no `.env` read) |
| CI | see the CI run for the pushed head |

## Flow

1. **Step 0** (read-only): `scripts/s13b_diagnose.py` rebuilds each question's ledger from the
   committed S4 dev records (both models) and re-runs the e072c38 validator on the recorded
   drafts. Every record matched (A1), so no question was excluded. Report:
   `eval/reports/s13b/diagnosis.md`. Header: "read-only diagnosis; no src change; agent sha
   unchanged".
2. **STOP 1:** multiple-choice decisions per fix (below).
3. **Step 1** (22d0ccc): the before-looking rules verbatim, the findings and the decisions in
   `post-pilot-fixes.md`.
4. **Steps 2–5:** one commit per approved fix, smallest blast radius first: F5, F4, F3, F2. Each
   commit pins the live agent sha in the same commit (A2). The full tests, ruff, mypy and
   `check_s0_stable.py` passed after each one.
5. **F2 mid-step question** (owner): alias names from a regex over the model's source file
   (extending `relation_names`), not from a compiled-SQL parse. Both give identical alias sets
   on every synthetic_shop model (checked).
6. **Step 8** (a9d5c77): ADR 0029, spec §0 row 37, the S1 design change-log note for F5.
7. **Step 9:**
   - Runner plumbing first, in its own commit (76b0825): `--prefix` and `--purpose`, defaults
     unchanged, tested. Nothing under `src/dlens/agent` changed.
   - Then **one** local qwen dev run. Estimated at 17–25 min with 0 cache hits (a new empty
     cache dir); actual: 96 records, 313 calls, 0 hits.

## Decisions (owner, 22 Oct 2026)

| fix | decision | step 0 basis |
|---|---|---|
| F1 R8 multi-hop | **DEFERRED**; option (d) recorded as design only | Consistent drops are joined only through indirect (JOIN/FILTER) edges. Bound 5 by the before-looking rule; (a) 1 / 55, (b) 0, (c) 1 |
| F2 R4 aliases | **APPROVED (a)**, source-file regex | 31 / 37 R4.hallucinated failures are alias tokens. `orders` names 3 models in dev-46's files. dev-44 #1 and dev-45 #0 pass too: inconsistent only via the alias token itself (case (i)), pinned as tests |
| F3 refused regenerate | **APPROVED (a)**, routing only | dev-75 only. Unchanged salvage keeps 2 claims; the verdict stays `no`, source `llm` (case (i): no `r_` fact, so R9 does not run) |
| F4 5-hex prefix | **APPROVED (a)** | dev-16 only: a unique, gold-consistent repair; nothing ambiguous |
| F5 transport errors | **APPROVED (a)** + A4 sub-item | The SDK error keeps the request (key header) as an object under `from exc` |
| F6 Ask refusals | **DEFERRED** (threshold STOP applied) | qwen dev-93–96 (unanswerable) refuse exactly where the code search_docs step would run; search_docs always returns hits |

## Commits

| commit | what |
|---|---|
| fc97c35 | step 0: diagnosis script + report |
| 22d0ccc | step 1: decisions, before-looking rules, findings |
| 59d22b3 | F5: Gemini transport errors → retryable `ProviderError`; nothing chained (A4); A2 sha pin |
| 9cdb11b | F4: `MIN_PREFIX_HEX` 7 → 5; record-replay test helper |
| 03c8837 | F3: refused regenerate → salvage |
| bac08bd | F2: R4 alias tokens are not node names (`provenance.alias_names`) |
| a9d5c77 | step 8: ADR 0029, spec row 37, S1 change-log note |
| 76b0825 | runner `--prefix` / `--purpose` (step 9 plumbing) |
| 0f069d1 | step 9: diagnostic run + report |
| this commit | this report |

## Tests

**Added** (all fixtures from committed records or synthetic stubs, no live model):

| file | covers |
|---|---|
| `tests/unit/agent/pilot_records.py` | helper: rebuilds a record's ledger on the CI fixture graph. Replays every validated round of both pilot records with 0 mismatches |
| `tests/unit/agent/test_gemini_transport.py` | F5: 4 transport errors → retryable; the sentinel key is in no text and in no `__cause__` / `__context__`; APIError 400 non-retryable, 429 retryable; other exceptions not mapped |
| `tests/unit/eval/test_s4_transport.py` | F5 end to end: one drop retried and answered; two drops → one failed record, and the runner continues |
| `tests/unit/agent/validator/test_prefix_repair.py` | F4: dev-16 repaired and passing; a twin 5-hex id ambiguous; a 4-hex prefix and a cross-kind prefix not repaired |
| `tests/unit/agent/loop/test_regenerate_refused.py` | F3: dev-75 salvaged (2 claims, source `llm`); the raw view stays the first draft; no passing claim → still a refusal; an R9 failure → `code` verdict; a first-draft refusal and a passing regenerate unchanged. 4 of 6 fail on the pre-F3 loop (checked) |
| `tests/unit/agent/validator/test_alias_tokens.py` | F2: the owner's regex cases (quotes, `ref('pkg','x')`, `source()`, implicit alias, 12 keywords); dev-46 (qwen, Gemini), dev-30, dev-44 #1, dev-45 #0; a non-alias token still fails; `foo_x.bar_y` and `fct_orders.net_paid_us` still fail; an alias that is a model name is checked as the model |
| `tests/unit/eval/test_s4_diagnostic_out.py` | runner `--prefix` / `--purpose`; defaults unchanged |

**Edited (sha pins only):** `tests/unit/eval/test_s4.py::test_pilot_reuse_holds_agent_code_unchanged_since_s12b`,
restructured per A2. Before: one assert, live sha == the qwen pilot manifest's. After: (i) the
manifest records `PILOT_AGENT_SHA` (`a6fb5b2e…`, frozen) and (ii) the live sha equals
`CURRENT_AGENT_SHA`, updated in each fix commit (`bffc02dc` → `4f9a069c` → `cefa5f0b` →
`77e25642`). The prompt-hash asserts are unchanged.

**A3 (pinned behaviour):** no existing test or snapshot row pinned a changed behaviour. With
`MIN_PREFIX_HEX = 5` and with `MAX_COMPLETION_HOPS = 5` applied in-process, every
`tests/unit/agent` test passed, the B3 outcome snapshot included. No snapshot row was edited.

**Guards:** every existing validator, loop and Gemini test passes unchanged. That includes R7,
the "directly" and sibling R8c tests, R2 on an unknown id, R4 on `fct.discount_pct`, the B3
outcome snapshot and the A2 raw-view pin.

Final local run: `make lint` clean; `make test` 1,617 passed, 19 skipped;
`check_s0_stable.py` 0 differences outside `timings.total_ms`.

## Frozen checks

- `s1.frozen_hashes() == FROZEN`: the three `tests/unit/eval/test_s1.py` asserts pass at every
  commit.
- `git diff --stat e072c38 -- ':(glob)eval/runs/s4/*.jsonl' ':(glob)eval/runs/s4/*.json'
  eval/runs/s1 eval/runs/s0 eval/reports/s13 eval/scores eval/metrics.py`: **empty**.
  - Written as in the brief (`eval/runs/s4/*.jsonl`, without `:(glob)`), the command lists one
    file: the new `eval/runs/s4/diagnostic/s13b-…-dev.jsonl`. A plain git pathspec `*` also
    matches `/`.
  - `git diff --name-only e072c38 -- eval/runs` lists only the two new diagnostic files. No
    pilot record or manifest changed.
- `git diff --stat e072c38 -- src/dlens/lineage src/dlens/retrieval
  src/dlens/agent/tools/entity.py eval/questions`: **empty** (engine, retrieval / chunker,
  linker, questions).
- `eval/questions/test.jsonl`, `external.jsonl` and their `.sha256` files: not opened, not
  edited.
- No cloud call, no `--allow-cloud`, no `.env` read. No absolute local path or username in a
  committed file (grep).

## Diagnostic summary (post-fix dev diagnostic; not a result)

`eval/reports/s13b/diagnostic_dev.md`, qwen, local, agent sha `77e25642`:

| row (validated view) | pilot | post-fix dev diagnostic |
|---|---|---|
| node-set F1 | 0.561 [0.47, 0.66] | 0.578 [0.49, 0.68] |
| trace F1 | 0.581 | 0.607 |
| hop 6+ | 0.364 | 0.373 |
| hallucination rate | 0.000 (69) | 0.000 (71) |
| citation valid (answer) | 0.899 | 0.901 |
| false refusal | 0.149 | 0.126 |
| yes/no · chain · clarify | 0.833 · 0.500 · 0.000 | 1.000 · 1.000 · 1.000 |
| Ask refusals | 5 / 12 | 5 / 12 |

The raw view is identical. Four questions moved, each attributed by its record:
- dev-16 (F4 repair);
- dev-46 (F2, refused → answered);
- dev-75 (F3, `+regenerate_refused`);
- dev-45 (F2, on a claim the audit called inconsistent only because of its alias token).

**Nothing moved the wrong way.** 8 first drafts (dev-17–28) differ from the pilot's with the
same evidence and prompts: model run-to-run variation at temperature 0, with no score change.

## Findings recorded, not changed (outside the approved files)

- `openai_compat.py` raises `from None` inside its `except` block, so its `__context__` still
  holds the httpx error and its request (`Authorization` header) as an object. Nothing prints
  it.
- `ollama.py` maps a connection error as non-retryable (status None).

## Carry-forward

- **S13c: F1 option (d) + F6 gate + linker items.**
  - **F1 option (d) design** (full text in post-pilot-fixes.md F1): R8c may traverse indirect
    edges where the family's traversal allowlist includes them (impact: direct + indirect;
    trace: direct only, as A5 / ADR 0026). The "directly" and sibling guards stay. Guards,
    negative tests and any bound are written before code, and the test set is the honest
    check.
  - **F6 next design** (full text in post-pilot-fixes.md F6): (1) a non-threshold gate first,
    running the code search_docs step only when the question resolves to a known node or doc
    term (dev-93 ties in with the linker list); (2) a hit-score threshold only if (1) cannot
    separate the cases, with the rule written and approved before any score distribution is
    computed. Fixtures: the 5 qwen Ask refusals and dev-93–96.
  - Both deferred fixes keep their full design and test lists in post-pilot-fixes.md.
- The two adapter findings above (openai_compat `__context__`, ollama retryability).
- The honest check of F2–F5 is the test set after the 7 Dec 2026 freeze, with these fixes
  frozen in the S4 system.
