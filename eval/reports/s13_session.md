# S13 session report: pilot (v0.3 done-when 5)

**Dates:** 21–22 Oct 2026. **Branch:** `s13-pilot` from main 7153bff (merged by the owner as
main 5c1b2fe); follow-up on `s13-ask-scores`.
**Design:** `docs/plans/pilot-design.md` v0.3 and its §3.1 run log. **Metrics:**
`docs/plans/metrics-design.md` v1.2, `eval/metrics.py` 1.3.0 (unchanged).
**Pilot table:** `eval/reports/s13/pilot_table.md`.

**Cloud LLM calls:** 530 Gemini calls, all run by the owner: S1 96 and S4 434, over two Pacific
days (21 Oct 475, 22 Oct 55; budget 475 a day). Claude Code made no cloud call and never passed
`--allow-cloud`.

**S4 pilot freeze:** in force from S12b (21 Oct 2026, 07:19 UTC). It **ends at commit 1c59483
(22 Oct 2026, 08:13 UTC)**, the commit of the pilot table. During the freeze nothing under
`src/dlens/agent` changed: the agent-code sha is `a6fb5b2e…` from S12b to 1c59483. S1 is frozen
(B8): `s1.frozen_hashes()` equals `FROZEN` at every commit. The linker and metrics.py did not
change. Test, external and their `.sha256` files were not touched.

## Pilot records (decided before any result, pilot-design §1)

| panel | S0 | S1 | S4 |
|---|---|---|---|
| qwen3:4b (local, temperature 0) | S0-gold, S0-linked hybrid on (committed) | fresh uncached re-run of frozen S1 v2, `eval/runs/s1/pilot/` (drafts byte-identical to S1 v2) | the S12b run, reused (agent-code sha equal to main's) |
| gemini-3.5-flash-lite (cloud, temperature 1.0, thinking unset) | same | new uncached run, one pass | new uncached run: 2 passes + a resume (see below) |

## Headline (node-set F1, mean [95% CI] (n = 68); S1 vs S4 within each panel only)

| row | qwen | Gemini |
|---|---|---|
| S0-gold | 1.000 | 1.000 |
| S0-linked (hybrid on) | 0.809 [0.71, 0.90] | 0.809 [0.71, 0.90] |
| S1 | 0.243 [0.17, 0.32] | 0.391 [0.30, 0.48] |
| S4 raw | 0.597 [0.50, 0.69] | 0.644 [0.55, 0.74] |
| S4 validated | 0.561 [0.47, 0.66] | 0.598 [0.50, 0.69] |
| S4 augmented | 0.625 [0.52, 0.72] | 0.724 [0.63, 0.81] |
| **S4 validated − S1** (paired) | **+0.318 [0.215, 0.420]** | **+0.208 [0.116, 0.298]** |
| McNemar, fully correct (S1 only / S4 only, n = 84) | 0 / 23, p = 2.4e-07 | 5 / 19, p = 0.0066 |

Every other row is in the pilot table: trace / impact F1, verdicts, refusals, evidence, cost, hop
buckets and losses. The two panels differ in model and in temperature, so no cross-panel test is
made.

## Steps and commits

| phase | commit | what |
|---|---|---|
| 0 | 6526b41 | pilot-design v0.1: pilot records fixed before any run |
| A | 901d14e, ef29d8d | prep audit script and test; audit of the S12b S4 run (dropped / rewritten / omitted claims by rule and gold class) |
| STOP A | eb2103c | owner: post-pilot fix candidates F1–F4 in pilot-design §4, no code |
| B1 | eb35b48 | shared `model_identity` and `quota_info` in S1 and S4 manifests (manifest only; B8 hashes and agent sha unchanged) |
| B2 | 3af180a | S1 qwen pilot run (uncached, 96/96) |
| B3 | 2fae190, 42a4376 | cloud plan v0.2, then v0.3 after the owner confirmed AI Studio limits (RPM 15, RPD 500 → B = 475) |
| B4 | dd1002a, e6a129b | `scripts/pilot_table.py` and the qwen panel |
| C | 8ae3284 | S1 Gemini (96/96, one pass) |
| C | 60758db | run log: S4 Gemini partial, transport-error gap recorded |
| D prep | 310b275, ad7438b, 5fb9164 | `scripts/ask_sheet.py`, `--panel all`, `docs/plans/post-pilot-fixes.md` |
| C | 1331d7e | S4 Gemini complete (96/96) + run log |
| D1 | 5950d91 | blind Ask sheet, unscored (key in gitignored `eval/cache/s13-ask-key/`) |
| D2 | f72ff2a, **1c59483** | all-fresh latency column, the pilot table: **freeze ends here** |
| D3 | this commit | this report |

## Gemini runs

- **S1:** one pass on 21 Oct, 96 calls, 0 cached, 0 errors.
- **S4:**
  - The first pass crashed at dev-38 on `httpx.RemoteProtocolError` (F5).
  - The resume ran until `QuotaExceeded` at dev-82, which used up 21 Oct's 475.
  - The partial file was not committed. The 22 Oct pass replayed 378 cached calls and made 55
    fresh ones.
  - dev-38 and dev-82 are split across passes.
- **Code refusals** (no LLM call, both models): dev-19 and dev-89–92.
- **LLM calls per question (S4):** qwen 3.32, Gemini 4.51.
- **Latency:** the cache does not store latency. Gemini S4 latency comes from the 10 all-fresh
  questions only (small n): p50 7.6 s, nearest rank (8.3 s interpolated). This includes waits on
  the 15-RPM limiter. metrics.py's own row (n = 15) also counts the 5 code refusals.

## Ask (M11)

**Deferred, not skipped.** The blind sheet `eval/scores/ask_pilot.csv` has 124 rows: 48 answers
(12 questions × S1 / S4 × qwen / Gemini, validated view), one row per gold fact, seed 20261021.
The key stays in the gitignored `eval/cache/s13-ask-key/ask_pilot_key.csv`. The pilot table's
Ask section said "pending owner scoring" (filled in by the follow-up below).

**Follow-up:** Ask means added in a docs-only commit after owner scoring; no record or code change.

## S12b observations: status

| # | observation | status |
|---|---|---|
| 1 | validation lowers F1, raises false refusals | holds on both models (qwen 0.597 → 0.561, Gemini 0.644 → 0.598); causes in the prep audit (F1–F3) |
| 2 | dev-46 refused by the validator | qwen only; R4 on a SQL alias (F2); Gemini answers it |
| 3 | chain 1.0 → 0.5 | qwen only (dev-16, truncated id, F4); Gemini 1.0 → 1.0 |
| 4 | augmentation raises impact F1 | holds, larger on Gemini (0.532 → 0.887; qwen 0.524 → 0.707) |
| 5 | search_docs rarely used | qwen 8 questions / 7 answers cite chunks; Gemini 22 / 11; value unmeasured until Ask is scored |
| 6 | spurious `uncovered_parts` | holds on both (qwen 4 / 68, Gemini 2 / 80), unscored |
| 7 | premise rejection 0.5, no flag | qwen 0.5 (prose only); Gemini 0.75, using the flag; one spurious flag on each model |

## Post-pilot fixes (design only; every decision pending)

`docs/plans/post-pilot-fixes.md`: **F1** R8 multi-hop claims (step 0: diagnose why R8c did not
complete them), **F2** R4 SQL aliases, **F3** refused regenerate goes to salvage, **F4** R2r
5-hex prefix repair, **F5** Gemini transport errors as a retryable `ProviderError`. All of them
change the agent-code sha. Each is checked by dev audit cases turned into unit tests, with no
dev re-score loop. The honest check is on test, after the 7 Dec 2026 freeze.

## Tests

| where | result |
|---|---|
| local `make lint` | ruff + format + mypy clean |
| local `make test` | 1,562 passed, 19 skipped |
| CI on `s13-pilot` | see the CI run for this commit |

## Draft resume line (draft, owner approves)

In the pilot table's last section. It uses committed numbers only (dev pilot, not test).

## Follow-up: Ask scores (branch `s13-ask-scores`, 22 Oct 2026)

As announced above: Ask means were added in a docs/data-only commit. No record or code change.

- **M11 deviation, recorded honestly.** The scores were produced by **Claude in the planner chat,
  authorised by the owner on 22 Oct 2026**, not hand-scored by the owner as M11 planned. The
  scorer was blind to the system labels (the key was unopened) and applied the sheet's header
  rule. The Claude model family is not a pilot system. Recorded in pilot-design §5 and the
  change log, and in the pilot table's Ask heading ("AI-scored (Claude), owner-authorised; not
  owner hand-scored"). The owner may re-score before v1.0; the owner's scores would then replace
  these.
- **Sheet check.** All 124 score cells were filled.
  - The owner's saved copy had `\n` line endings, where the original had `\r\n`
    (`csv.DictWriter`'s default, on the column header and the 124 rows). So git showed 125
    changed lines, every CSV line.
  - The file was rewritten in the original format. Now only the 124 score cells differ (124
    changed lines), and every other field of every parsed row equals the unscored sheet
    (5950d91).
- **Key** moved from `eval/cache/s13-ask-key/` to `eval/scores/ask_pilot_key.csv`.
- **Ask means** (mean over the 12 answers; answer = mean over its facts; refusals 0):

| system | qwen3:4b | gemini-3.5-flash-lite |
|---|---|---|
| S1 | 0.660 [0.46, 0.85] | 0.729 [0.55, 0.89] |
| S4 | 0.306 [0.12, 0.53] | 0.639 [0.42, 0.83] |

  S4 is below S1 on Ask on both models. Refused Ask answers: S4 qwen 5 of 12, and 1 each for the
  others. No S1 vs S4 test is run on Ask (n = 12, AI-scored).
- **Hand edits.** `pilot_table.md` was regenerated by `scripts/pilot_table.py --panel all`, and
  then its Ask heading and paragraph were edited by hand. `pilot_qwen.md` and `pilot_gemini.md`
  got one line each, also by hand. The script still writes "hand-scored by the owner" as a fixed
  string, so a regeneration must repeat the edit until a code change fixes it (follow-up).
- **Resume line:** unchanged, and it does not mention Ask or hand-scoring.
