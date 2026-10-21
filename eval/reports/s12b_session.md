# S12b session report: agent upgrades G1–G4 + B5–B8

**Dates:** 20–21 Oct 2026. **Branch:** `s12-agent-goals` from main 5f87f8e (pushed, not merged).
**Design:** `docs/plans/s12-design.md` v1.3. **Metrics:** `docs/plans/metrics-design.md` v1.2
(Accepted), `eval/metrics.py` 1.3.0. **Cloud LLM calls:** 0 (local `qwen3:4b-instruct-2507-q4_K_M`
only). **S4 pilot freeze:** in force from the start of the full dev run (21 Oct 2026, 07:19 UTC)
until S13 is done: S4 changes only for recorded crash-class bugs.

## Changes and decisions

| step | commit | what |
|---|---|---|
| 1 | 2bd1093 | metrics-design v1.2 draft (M9, M10, Appendix D), ADRs 0025/0027/0028 text, s12-design v1.2 (step order, pilot freeze, exact `ALLOWED_DIFFERENCES`) |
| STOP 1 | 5b389ae | Owner: v1.2 approved with one change (M9 mention branch uses pre-mention negation only: "No, G does not reach H" names G); Appendix D results fixed as the definition |
| B8 | 44f4a66 | Engine-agreement star-citation test ingests a tmp copy of synthetic_shop, runs in CI (`integration`, lint-test) |
| B3 | 9c39f0b | `premise_corrected` (LLM only) and claim `origin` (`model` / `repaired` / `completed` / `augmented` / `verdict`). Labels only: every validate/salvage call of the validator tests matches a snapshot recorded on the pre-B3 code (106 tests, 81 calls) |
| B4 | 652e40c | `search_docs` in S4 only with an index; `c_` in `_ids_in`, the ledger, evidence, a digest, R2/R2r, R3 (S1's ledger rule; all 506 fixture chunks pass). **Owner decision during B4:** R4 evidence also takes a shown hit's own entity (never a name only in its text); chunk-only lineage claims still fail R8 |
| B1 | dfc1227 | G1 coverage completion (`augment.py`): trace direct inputs and impact side-set columns the answer left out, `origin: augmented`, from the tool log only; spec §8 note |
| B2+B5 | 0207837 | `uncovered_parts` (LLM; prompt line with no example), `interpretation {from, to}` + `interpretation_source` (code); metrics.py 1.3.0 per v1.2 |
| B6 | 8d7b077 | Name words settle a tie ("raw customers" → `raw_customers`, longest names first); `r_` fact from linked columns. **Owner addition during B6:** "upstream of" / "downstream of" / "derived from" cue the fact (spec §7 lines 284–285, §8 lines 319–320, `DERIVES` line 236) |
| B7 | 28f60c6 | Per-candidate mode code-traces each tied candidate (`candidate_trace`); no evidence → clarification, not refusal |
| 3 | 302f272, d7a3c16, 28f6f5e, e9c2768 | `s0.py --hybrid` (new files), S0-linked hybrid-on records, tool-phase budget replay, ADRs 0025/0027/0028 Accepted (spec §0 rows 34–36), metrics-design v1.2 Accepted |
| STOP 2 | 4d5974d, c007759 | Manifest model identity (owner pre-run check 2); `scripts/check_s4_repro.py` + test |
| 5 | this commit | Full uncached S4 dev run, reproducibility pass, reports in `eval/reports/s12b/`; repro script fix (records with 0 LLM calls have no cache state) |

## Tests

| where | result |
|---|---|
| local `make test` (agent + ui + retrieval extras) | 1,538 passed, 19 skipped (after the repro-script fix and its test) |
| CI lint-test 3.12 / 3.13: `make test` | 1,486 passed, 38 skipped (each) |
| CI lint-test 3.12 / 3.13: core install, no extras | 853 passed, 8 skipped, 72 deselected (each) |
| CI retrieval | 94 passed |
| CI core-artifacts macOS / Windows | 56 / 56 passed |
| CI demo-install | success |

CI run 39560543623 on c007759 (the head the run started from): all six jobs green. Appendix D:
all 51 rows pass against the real extractor on the first run, no row or rule tuned.

## Checks (no LLM)

- **S1 frozen:** `git diff main -- eval/systems/s1.py eval/questions` is empty;
  `s1.frozen_hashes() == FROZEN` (system `fb820558…`, schema `60364350…`, citation_rule
  `159a0020…`, all eight equal).
- **S0 stability** (`scripts/check_s0_stable.py`, hybrid off): s0-gold 84 records, 0 differ outside
  `timings.total_ms`; s0-linked 84 records, 0 differ outside it. Committed files untouched.
- **Existing reports under metrics 1.3.0:** the committed S0-gold, S0-linked, S1 v2 and S4 smoke
  reports re-score with only the v1.2 additions (new rows `uncovered_part_correct` /
  `interpretation_correct`, the pass-route and spurious-field tables and their diagnostics); no
  existing value changed or disappeared (`test_report_regression.py`, S0 and S1).
- **Paths / usernames:** the branch diff against main (lock files excluded), 3,100 added lines:
  no Linux / macOS / Windows home-path prefix, no bare username outside the repo and Streamlit
  URLs.
- **Prompt growth:** answer system + draft schema 591 → 726 est. tokens (+135: B2 + B3 lines and
  properties, the `c_` phrase); tool-phase fixed cost 721 → 850 est. with an index (+129).

### Model identity (S4 manifest, `model_identity`)

| field | value |
|---|---|
| model | `qwen3:4b-instruct-2507-q4_K_M` |
| Ollama digest | `0edcdef34593eac1aa2be9c7d06c432dcf81945adca5eca2f27662c18f168ba0` |
| Ollama version | 0.35.1 |
| sampling sent | temperature 0, num_ctx 8192, think off, **no seed** |
| Modelfile defaults | top_k 20, top_p 0.8, repeat_penalty 1, temperature 0.7 (overridden by the call's 0), stop `<|im_start|>`, `<|im_end|>` |

**S13 note:** the S1 pilot run records the same fields (s1.py not touched in S12b).

### Trim counts (offline replay, `scripts/replay_answer_budget.py`)

18 Oct tool calls, today's tools; answer phase with the S12b prompt and the 278 reserve:

| threshold | trimmed |
|---|---|
| cap (no reserve) | 2 / 67 (dev-67, dev-69) |
| cap − 278 (A6, S12b prompt) | **3 / 67** (dev-09, dev-67, dev-69); S12a: 2 / 67 |
| cap − 803 (rejected) | 5 / 67 |

The live run trimmed the same three (`partial_evidence` on dev-09, dev-67, dev-69).

**Tool phase (owner amendment 6), hybrid on, search_docs in the specs:** 216 calls rebuilt, max
2,668 est. before compaction (dev-75), 0 compactions needed, **0 over the 3,000 cap**. Live: the
largest request of the run was 2,909 est. (dev-72's regenerate); no call over the cap.

## The full run

- **Run 1 (uncached):** `DLENS_PROVIDER=ollama DLENS_CACHE_DIR=eval/cache/s4-s12b uv run --extra
  agent --extra retrieval python eval/systems/s4.py`, new empty cache, hybrid on (index reused),
  at c007759. 96 records, **319 local LLM calls, 0 cached** (91 records `miss`; 5 refused before
  any call: unknown column, `cache` null). ~17 min wall clock. Records + manifest:
  `eval/runs/s4/s4-qwen3-4b-instruct-2507-q4-k-m-dev.*`.
- **No crash-class failure:** no Python exception; no `ProviderError` / `QuotaExceeded` /
  `InputTooLarge` in any record. Record errors are answer outcomes: 11 "no lineage evidence", 2
  "no verifiable claims", 5 unknown-column refusals (the unanswerable questions).
- **Reproducibility pass** from the same cache into `eval/cache/s4-s12b-repro-out/`
  (gitignored): 96 records, **0 uncached calls**, every record equal to run 1 outside the excluded
  fields (`run_id`, `started_at`, `timings`, `steps[].latency_ms`, `steps[].cached`, `cache`,
  `tokens.cached_calls`). This proves the records are **reproducible from the cache**, not that
  the model is deterministic: a second uncached run may answer differently.
  - Found on the way, fixed in the check script only: the first comparison flagged the 5 records
    with 0 LLM calls (their `cache` is null in both passes, not `hit`). The rule now requires
    `hit` only for records with LLM calls (test added). No record or S4 code changed.
- **Regenerates (A6's first live test):** 22 records took the validator's regenerate. **0
  `+regenerate_skipped_budget`**. R9 failed on no first draft (0 R9 regenerates).
- **dev-67:** no search_docs call, so no `c_` evidence; impact payload 2,433 est. in the second
  tool call; answer prompt trimmed to 2,720 est. (limit 2,722), not refused.
- **search_docs:** called on 8 questions (dev-27, 28, 51, 57, 62, 63, 80, 85), 8 calls; 7 final
  answers cite a `c_` id.
- **Code rules:** `reachability_fact` 6 (dev-10, 50, 72, 73, 74, 76: the offline B6 recount's 6),
  `candidate_trace` 5, `code_evidence` 7, `linked_evidence` 4, `chain_trace` 3.
- **Claim origins (final answers):** model 232, repaired 17, completed 19, verdict 2, augmented 69
  (in 14 answers).
- **Latency (uncached, 96 runs):** p50 8.9 s, p95 30.4 s per question.
- **Tokens:** 3,502 per question (input + output, mean), p95 7,020; LLM calls 3.32 per question.

### S13 quota estimate (from measured calls)

S4 on dev: 3.32 calls per question × 96 = **~319 calls** for one S4 pass on Gemini, if Gemini's
call pattern matches qwen's (it may not: regenerates and tool turns depend on the model).
Bounds: worst case 768 (8-call cap × 96). This replaces the ≤ ~487 design estimate. S1 unchanged
(96 / 192).

## Scores

> **dev, report only; the pilot table is S13.** No S4 change is made for any number below (pilot
> freeze). Full reports with M13 CIs, breakdowns, pass routes, spurious-field lines and the
> linker-test-seen flag: `eval/reports/s12b/`.

| metric (dev, report only; the pilot table is S13) | S0-gold | S0-linked hybrid off | S0-linked hybrid on | S1 v2 | S4 raw | S4 validated | S4 augmented |
|---|---|---|---|---|---|---|---|
| node-set F1 (n=68) | 1.000 | 0.868 [0.78, 0.94] | 0.809 [0.71, 0.90] | 0.243 [0.17, 0.32] | 0.597 [0.50, 0.69] | 0.561 [0.47, 0.66] | 0.625 [0.52, 0.72] |
| trace F1 (n=44) | 1.000 | 0.909 | 0.864 | 0.270 | 0.613 | 0.581 | 0.581 |
| impact F1 (n=24) | 1.000 | 0.792 | 0.708 | 0.193 | 0.568 | 0.524 | 0.707 |
| yes/no (n=6) | 1.000 | 1.000 | 1.000 | 0.500 | 1.000 | 0.833 | 0.833 |
| refusal correct (n=9) | 1.000 | 1.000 | 0.889 | 0.556 | 1.000 | 1.000 | 1.000 |
| false refusal | 0.000 (75) | 0.107 (75) | 0.013 (75) | 0.011 (87) | 0.115 (87) | 0.149 (87) | 0.149 (87) |
| chain (n=2) / clarify (n=1) | 1 / 1 | 1 / 1 | 1 / 1 | 0 / 0 | 1 / 1 | 0.5 / 0 | 0.5 / 0 |
| premise rejected (n=4) | 1.000 | 1.000 | 1.000 | 0.250 | 0.500 | 0.500 | 0.500 |
| uncovered part (n=3) | 0.000 | 0.000 | 0.000 | 1.000 | 1.000 | 1.000 | 1.000 |
| path node coverage (n=29) | 1.000 | 0.897 | 0.862 | 0.207 | 0.552 | 0.483 | 0.483 |
| hallucination rate | 0.000 | 0.000 | 0.000 | 0.004 | 0.005 | 0.000 | 0.000 |
| citation valid (per answer) | 1.000 | 1.000 | 1.000 | 0.533 | 0.616 | 0.899 | 0.914 |
| latency p50 / p95 (s) | – | – | – | 9.3 / 13.7 | 8.9 / 30.4 | 8.9 / 30.4 | 8.9 / 30.4 |

**Pass routes** (dev, report only; the pilot table is S13; field / prose / both / neither):

| rule | S0 (all three) | S1 v2 | S4 raw | S4 validated | S4 augmented |
|---|---|---|---|---|---|
| uncovered part (n=3) | 0 / 0 / 0 / 3 | 0 / 3 / 0 / 0 | 0 / 0 / 3 / 0 | 0 / 0 / 3 / 0 | 0 / 0 / 3 / 0 |
| premise rejection (n=4) | 0 / 4 / 0 / 0 | 0 / 1 / 0 / 3 | 0 / 2 / 0 / 2 | 0 / 2 / 0 / 2 | 0 / 2 / 0 / 2 |
| interpretation | n/a (0 dev questions) | n/a | n/a | n/a | n/a |

S4 gains nothing on dev from the structured fields alone: every uncovered-part pass is `both`
(the prose branch would have passed too), and no premise rejection came through the field.
**Spurious fields (S4, not scored):** non-empty `uncovered_parts` on non-multi-part questions:
raw 5 / 71, validated 4 / 68; `premise_corrected = true` off false-premise questions: 1 / 72 raw,
1 / 69 validated.

**Linker-test-seen flag** (S4 validated node-set F1): flagged 0.418 (n=14), not flagged 0.598
(n=54).

### S0-linked hybrid off vs hybrid on (diagnostic; dev, report only; the pilot table is S13)

The pilot table uses hybrid on (one flag with S4, M14). 12 questions change, all to
`clarification`: dev-21, 27, 28, 51, 57, 62, 63 and dev-93 were refusals (linker no-match) and
become clarifications; dev-29, 40, 56, 71 were answered (F1 1.0) and become clarifications. Net:
node-set F1 0.868 → 0.809, false-refusal rate 0.107 → 0.013, refusal accuracy 1.000 → 0.889
(dev-93, an unknown-model question, now gets a clarification). The hybrid stage turns no-matches
into ties, as designed in S08; whether that trade is right is a linker question for after the
pilot (linker frozen).

## Known limits (recorded, no change)

- **B4 single-column chunk-only gap:** a one-column claim with a lineage word that cites only
  `c_` ids ("A is derived from raw data") names no second column, so no rule catches it: R8 needs
  two columns, R5 checks kind words only against cited edges. The same gap exists today for `s_`
  excerpts. Recorded in `docs/explain/validator.md`.
- **dev-75's hybrid tie:** with the linker's hybrid stage on, "customer segment in customer
  leaderboard" ties `fct_customer_leaderboard.full_name` (0.852) over `customer_segment` (0.84),
  so B6 cannot link it and dev-75 gets no `r_` fact (hybrid off it would). In the run dev-75 went
  per-candidate (3 candidate traces), took a regenerate and ended `+candidates_ignored`. The
  linker is frozen until after the pilot.

## Answer-quality observations for S13 (no code change: pilot freeze)

1. **Validation lowers node-set F1** (raw 0.597 → validated 0.561) and raises the false-refusal
   rate (0.115 → 0.149): dropped claims and two "no verifiable claims" refusals (dev-43, dev-46).
   Worth reading the dropped claims by rule before the pilot.
2. **dev-46 (B7):** B7 worked as designed (resolve, then two `candidate_trace` steps, evidence
   found), and the raw draft answered per candidate (clarify correct in raw), but every claim
   failed validation and the run ended refused. The refusal moved from "no lineage evidence" to
   the validator.
3. **Chain:** raw 1.0 → validated 0.5 (one of dev-16 / dev-31 lost its target mention in
   validation).
4. **Impact augmented gain:** impact F1 0.524 → 0.707 with G1, so the tools found far more than
   the model named; trace F1 does not move (missing direct inputs were rare).
5. **search_docs** was used on 8 questions only; 7 answers cite chunks. Ask questions are hand
   scored (M11), so this run does not measure what the chunks added.
6. **Spurious `uncovered_parts`** on 4–5 non-multi-part answers (e.g. dev-75 lists two parts of a
   yes/no question): unscored, but the S13 report should keep the line.
7. **premise rejection 0.5:** two of four false-premise questions pass through prose; no
   `premise_corrected` flag on any of them, and one flag set on a non-premise question.

## Files

- Records: `eval/runs/s4/s4-qwen3-4b-instruct-2507-q4-k-m-dev.{jsonl,manifest.json}`,
  `eval/runs/s0/s0-linked-hybrid-dev.{jsonl,manifest.json}` (S0-linked hybrid-off files untouched).
- Reports: `eval/reports/s12b/` (S4 raw / validated / augmented, S0-gold, S0-linked hybrid off and
  on, S1 v2 re-scored). The committed reports in `eval/reports/` are untouched.
