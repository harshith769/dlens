# S13d design: M7 vs validator, variance seeds, S2 and S3 systems, C1, freeze checklist

**Version:** 0.1 (23 Oct 2026). **Status:** design only; **every Decision is PENDING** (owner).
**Branch:** `s13-s2s3-design` from main `084135e` (matches CI's `s[0-9][0-9]-*`).
**Inputs:** spec §0, §8, §11.3–11.7, §13; `docs/plans/v0.3-plan.md`; `s1-design.md`;
`s12-design.md`; `s13c-design.md` (§S seed); `metrics-design.md` v1.2;
`eval/reports/s13c_session.md` (the M7 diagnosis); `eval/systems/s1.py`, `s4.py`, `manifest.py`;
`src/dlens/agent/loop.py`.
**Measurements:** `scripts/s13d_measure.py` (read-only). Every number below comes from it and is
labelled as offline (no LLM) or local (local Ollama only).

| part | kind | what it reads / sends |
|---|---|---|
| `m7` | offline | committed pilot and diagnostic records, the corpus files, the S07 index chunks |
| `s3` | offline | committed S4 records |
| `s2tokens` | offline | the S07 index chunks; set E built and chunked in a scratch `--work` dir |
| `qwenfit` | local | one S2 prompt (the dev-01 question) to local qwen, one send per num_ctx rung |
| `seeds` | local | the S13c 12 saved answer prompts, 4 sends each |

Rules that held throughout this session:
- No cloud call; no `--allow-cloud`; no `.env` read.
- `eval/questions/test.jsonl`, `external.jsonl` and their `.sha256` files were not opened (they
  do not exist yet). No test question was generated or printed.
- `eval/metrics.py` 1.3.0 and metrics-design v1.2 are unchanged.
- No pilot, diagnostic or baseline record was rewritten.
- No code under `src/` or `eval/systems/`.
- The two local parts send straight through `ollama.Client`, as `s13c_measure.py --part seed` did.
  `LLMClient`'s 3K cap would refuse the S2 prompt, and that refusal is the thing being measured.
  No system run or question-set run was made.

---

## Decision list (owner)

| # | decision | options | recommendation | one-line reason |
|---|---|---|---|---|
| 1 | M7 vs validator on `c_` / `s_` citations | (a) report the split / (b) align M7 to the chunk rule / (c) align the validator to M7 | **(a)** | Under (b), S1's citation validity (citations attached by code, no relevance check) becomes nearly true by construction (qwen 0.533 → 0.967); (c) empties 4–5 S4 answers that passed the validator (Ask, computed, impact) |
| 2 | Primary seed | 42 (as today) | **42** | Already in every manifest; S1 and S4 alike |
| 3 | qwen variance runs | (i) drop as not informative / (ii) seed-null runs / (iii) a temperature change (**not allowed**) | **(i)** | At temperature 0, seeds 43 and 44 changed **0 / 12** outputs. A seed (or no seed) is therefore no way to re-create run-to-run noise. The one variation measured (2 / 12) comes from KV-cache state |
| 4 | Gemini variance runs | seeds 43, 44; S1 + S4; temperature 1.0 with the seed | **as proposed** | The only model where a seed changes sampling. 720 calls |
| 5 | Variance subset rule (applied only at the freeze) | type × hop bucket strata, Ask in or out | **strata as §2.3, Ask excluded** | Ask is judge- or hand-scored; its noise is the judge's, not the system's |
| 6 | S2 corpus content | model chunks / model + doc / **all chunks** (S1's universe) / raw compiled files | **all chunks** | S2 then sees exactly what S1 retrieves from, so S2 − S1 = "retrieval vs stuffing". Column descriptions exist only in column cards |
| 7 | S2 input cap (recorded exception to ~3K) | per-provider rule (§3.2) | **Gemini 240,000 est.; qwen num_ctx − 1,024 real** | Gemini: under TPM 250K with a 10K margin. qwen: the server's own limit (it rejects, never truncates) |
| 8 | S2 on qwen | run at num_ctx 32768 (S2 only) / report "doesn't fit on a 6 GB GPU" | **run at 32768** | Measured: fits, 28,930 real tokens, 54% GPU / 46% CPU, ~146 s per question. Free; ~9 h for test, overnight |
| 9 | S2 on set E | Gemini: run / skip. qwen: — | **Gemini run (60 calls); qwen "doesn't fit on a 6 GB GPU"** | Set E is 123,917 est. tokens: under TPM, but far above the 65,536 ladder cap |
| 10 | **Owner TODO (read-only, no API call):** "Owner reads the AI Studio rate-limit page for gemini-3.5-flash-lite in project dlens-eval and reports any TPD limit" | – | – | S2 test needs ≈ 7.56M est. tokens, plus ≈ 7.44M for set E (§3.5). A TPD under that splits S2 over several days |
| 11 | TPM pacing in `src/dlens/agent/llm` | build before the freeze / no S2 on Gemini | **build before 7 Dec** | 15 RPM × 33.7K = 506K tokens/min, about twice the 250K TPM. It moves `agent_code_sha256` (A4, §3.3) |
| 12 | S3: `search_docs` tool | keep / drop | **drop** | Docs retrieval is part of what S3 must exclude |
| 13 | S3: F6 code docs step | keep / drop | **drop** | It is a `search_docs` call by code: retrieval |
| 14 | S3: linker hybrid stage | keep / drop (stages 1–2 only) | **drop** | Dense search over column cards is retrieval |
| 15 | S3: validator (R1–R9, R2r, R8c, regenerate, salvage) | keep / drop | **keep** | S4 − S3 must isolate retrieval, not the validator; the no-validator ablation already exists as S4-raw |
| 16 | S3: coverage completion (G1) and the three views | keep / drop | **keep** | Same reporting shape as S4, so S3-validated vs S4-validated compares like with like |
| 17 | S3: code steps (chain trace, R9 fact, unknown-column refusal, ambiguity policy, code / linked evidence, candidate trace) | keep / drop | **keep** | Graph-only by construction (none reads the index) |
| 18 | C1 go / no-go and timing | go in S16 / go in Buffer A / v1.0 / no-go | **go, in S16; pin dbt-colibri 0.3.7** | No LLM, no freeze dependency, MIT; a v1.0 deliverable, so doing it early leaves room for surprises |

`Decision:` PENDING for every row.

---

## 1. M7 vs the validator on chunk and excerpt citations

**The gap (S13c diagnosis).**
- **The validator (R3)** accepts a line-level `c_` citation when the lines name the **chunk's own
  entity**. A model SQL chunk only has to cite its model's own file. An `s_` excerpt is checked
  by its text hash.
- **The metric (M7)** sends every non-edge citation down its excerpt branch
  (`eval/metrics.py:704–706`). There, the lines must name **a dotted column the claim itself
  names**.
- So a claim that names no dotted column ("the order status group is set by a CASE") can never
  pass M7.

### 1.1 Measured (offline, committed records, `--part m7`)

**(a) The split.** The first column is per-answer M7 exactly as scored. The script asserts it
equals `score_run`'s `citation_valid_answer`, per question and on the mean. n = answered answers.
- "Dotted only" = validity over citations first cited by claims that name a dotted column.
- "None only" = validity over citations first cited by claims that name none.
- An answer can be in both.

| records | view | M7 per answer (as scored) | dotted-claim citations only | no-column-claim citations only | micro `c_`/`s_`, dotted claims | micro `c_`/`s_`, no-column claims |
|---|---|---|---|---|---|---|
| S1 qwen pilot | validated | 0.533 (90) | 0.886 (70) | **0.000 (34)** | c_ 168/178 | c_ 1/84 |
| S1 Gemini pilot | validated | 0.885 (78) | 0.921 (76) | 0.000 (3) | c_ 223/229 | c_ 0/4 |
| S4 qwen pilot | raw | 0.616 (73) | 0.723 (65) | 0.375 (16) | c_ 4/4, s_ 1/1 | c_ 1/11, s_ 0/2 |
| S4 qwen pilot | validated | 0.899 (69) | 1.000 (61) | 0.500 (12) | c_ 6/6, s_ 1/1 | c_ 1/7, s_ 0/2 |
| S4 qwen pilot | augmented | 0.914 (70) | 1.000 (63) | 0.500 (12) | c_ 6/6, s_ 1/1 | c_ 1/7, s_ 0/2 |
| S4 Gemini pilot | raw | 0.890 (82) | 0.949 (78) | 0.500 (4) | c_ 16/18, s_ 28/30 | c_ 0/1, s_ 0/1 |
| S4 Gemini pilot | validated | 0.938 (80) | 1.000 (76) | 0.400 (5) | c_ 16/16, s_ 24/24 | s_ 0/5 |
| S4 Gemini pilot | augmented | 0.951 (81) | 1.000 (78) | 0.400 (5) | c_ 16/16, s_ 24/24 | s_ 0/5 |
| S4 qwen post-S13c (diagnostic) | raw | 0.613 (80) | 0.725 (69) | 0.400 (20) | c_ 8/8, s_ 1/1 | c_ 1/18, s_ 0/2 |
| S4 qwen post-S13c (diagnostic) | validated | 0.885 (78) | 1.000 (68) | 0.529 (17) | c_ 12/12, s_ 1/1 | c_ 1/10, s_ 0/2 |
| S4 qwen post-S13c (diagnostic) | augmented | 0.899 (79) | 1.000 (70) | 0.529 (17) | c_ 12/12, s_ 1/1 | c_ 1/10, s_ 0/2 |

Two runs requested in the brief do not exist:
- **S1 post-S13c:** S1 is frozen (B8) and was not re-run.
- **S4 Gemini post-S13c:** no Gemini run after S13c.

The split is therefore shown on the five record sets that exist.

What the split says:
- The gap is **mostly an S1 qwen effect**. S1 qwen writes many claims with no dotted column
  (84 chunk citations; 1 is M7-valid), so 34 of its 90 answered answers fail M7 on such a claim.
  On dotted-column claims alone S1 qwen scores 0.886.
- S4-validated is 1.000 on dotted claims on every record set. Its losses are all no-column
  claims.

**(b) Hypothetical: M7's excerpt branch replaced by the validator's chunk rule.** The chunk rule
is re-implemented in the script. M7's file, bounds, model-level and star rules are unchanged.
**Not a rescoring:** the committed pilot table (`eval/reports/s13/pilot_table.md`) is **not**
recomputed. This lists what would differ if it were:

| records | view | M7 today | under (b) | answers that change (all 0 → 1) |
|---|---|---|---|---|
| S1 qwen pilot | validated | 0.533 | **0.967** | 39 answers (dev-08, 14, 15, 16, 20, 21, 24, 27, 29, 33, 37–39, 41–47, 49, 51, 56, 57, 60, 62, 63, 66, 68, 70, 75, 78, 79, 84–88, 91) |
| S1 Gemini pilot | validated | 0.885 | **1.000** | dev-20, 36, 42, 65, 73, 76, 77, 86, 87 |
| S4 qwen pilot | raw | 0.616 | 0.685 | dev-12, 42, 62, 63, 85 |
| S4 qwen pilot | validated | 0.899 | 0.986 | dev-12, 27, 42, 57, 63, 85 |
| S4 qwen pilot | augmented | 0.914 | 1.000 | as validated |
| S4 Gemini pilot | raw | 0.890 | 0.902 | dev-45 |
| S4 Gemini pilot | validated | 0.938 | 0.975 | dev-45, 86, 88 |
| S4 Gemini pilot | augmented | 0.951 | 0.988 | as validated |
| S4 qwen post-S13c | validated | 0.885 | 0.987 | dev-12, 27, 42, 57, 63, 84, 85, 86 |

**Pilot table cells (b) would change** if the table were recomputed:
- "citation valid (answer)" for S1, S4-raw, S4-validated and S4-augmented, both panels;
- the micro citation validity;
- the R3-disagreement count.

These do **not** change: no F1, no refusal or verdict metric, and not "fully correct"
(`metrics.py:948`: headline F1 only).

**(c) Validator aligned to M7: validator-kept claims that would fail.** S4-validated view, claims
of origin model / repaired / completed. This is a **static estimate**: regenerate and salvage are
not re-run, so the real outcome could differ.

| records | claims that would fail / kept model claims | answers emptied (all their claims fail) |
|---|---|---|
| S4 qwen pilot | 8 / 267 | 4 (dev-27, 42, 63, 85) |
| S4 Gemini pilot | 5 / 202 | 2 (dev-86, 88) |
| S4 qwen post-S13c | 11 / 292 | 5 (dev-27, 42, 63, 84, 85) |

An emptied answer goes to regenerate, then to salvage or a "no verifiable claims" refusal.
dev-84 and dev-86 are the F6 docs-based Ask answers of the S13c diagnosis. The others are not all
Ask: dev-27 and dev-42 are trace/computed, dev-63 is impact, and dev-85 and dev-88 are Ask. Each
has claims that cite a chunk or excerpt but name no dotted column.

### 1.2 Options

| | (a) report the split | (b) align M7 to the validator's chunk rule | (c) align the validator to M7 |
|---|---|---|---|
| What changes | The report scripts (`scripts/pilot_table.py` and the v1.0 results script) add two columns: per-answer citation validity on dotted-claim citations and on no-column-claim citations, computed from records with the M3 extractor. `metrics.py` and the headline M7 are unchanged | metrics-design M7 v1.3: the excerpt branch (M7 step 3, "excerpt citation") becomes "a column card's lines name its column; a model description's lines name its model; a model SQL chunk is in its model's file; other docs have no entity; `s_` by text hash". `metrics.py` needs chunk metadata, which S1 records do not hold, so it would read the S07 index `chunks.jsonl` (a new input, keyed by the index key) | Validator R3 for `c_` / `s_`: the cited lines must also name a column the claim names (or a claim that names none fails) |
| Rule 12 (S1 symmetry) | Holds: one metric for every system, unchanged | Holds formally (one rule for all). But for S1 the rule is nearly true by construction: S1's citations are attached by code from the shown chunks, and S1 has no R7 relevance check. Only M7's current "names a column of the claim" test links an S1 claim to its chunk | Holds for the metric. The validator is S4-only, so S1 is unaffected and S4 gets stricter |
| Pilot numbers | None change; the split is new, labelled columns | The cells above would differ. The committed pilot table is **not** recomputed; a v1.3 table would be a new file next to it | S4 records unchanged (no re-run); a re-run would lose the claims above |
| Before the freeze | Report-script change only; any session | Owner-gated metrics change (CLAUDE.md: the approved plan must name `eval/metrics.py`); metrics-design change log; `__version__` 1.4.0; tests; must land before 7 Dec | Owner-gated validator rule change; `agent_code_sha256` moves; `CURRENT_AGENT_SHA` re-pinned; explain-back update; before 7 Dec |
| After the freeze | Allowed: reporting only, no system or metric change | Not allowed (metric definitions are fixed with the test set) | Not allowed (system freeze) |
| Files | `scripts/pilot_table.py` (+ the S16 results script), `docs/explain/metrics.md` (reporting note) | `docs/plans/metrics-design.md`, `eval/metrics.py`, `tests/unit/eval/test_metrics*.py`, `docs/explain/metrics.md` | `src/dlens/agent/validator.py`, `tests/unit/agent/validator/*`, `docs/explain/validator.md`, `tests/unit/eval/test_s4.py` (sha) |

**Recommendation: (a).** One line: (b) would make S1's citation validity nearly true by
construction (qwen 0.533 → 0.967), hiding the one relevance signal S1 has; (c) would empty 4–5
S4 answers that passed the validator. The split shows the same facts without changing a definition.

`Decision:` PENDING.

---

## 2. Variance runs and seeds (spec §11.6: "2 extra S1 + S4 runs on the 60-question variance subset")

### 2.1 Proposal as briefed
- Primary run: seed 42.
- Variance runs: seeds 43 and 44, S1 and S4 alike, both models.
- Gemini stays at temperature 1.0 with the seed.

### 2.2 Measured first: does a seed change qwen's output at temperature 0? (local, `--part seeds`)

**Protocol.**
- The S13c 12 answer prompts (dev-17, 18, 20, 21, 22, 24, 27, 28 and the controls dev-01–04),
  rebuilt once on today's tools and saved.
- Per prompt, strictly one request at a time, in this order:
  - seed 42: the prompt's first send, fresh KV cache;
  - seed 42 again: the prompt is now a cached prefix;
  - seed 43;
  - seed 44.
- Model `qwen3:4b-instruct-2507-q4_K_M`, temperature 0, num_ctx 8192, Ollama 0.35.1.

| id | 42b = 42a (cache state) | 43 = 42b | 44 = 42b |
|---|---|---|---|
| dev-17, 18, 20, 22, 24, 27, 28, dev-01, 02, 04 | yes | yes | yes |
| dev-21 | **no** | yes | yes |
| dev-03 | **no** | yes | yes |

- **A different seed changed the output on 0 / 12 prompts.** At temperature 0 qwen decodes
  greedily, so the seed has no effect on the output.
- **The KV-cache state changed it on 2 / 12.** The first send of a prompt (fresh evaluation) and a
  re-send (cached prefix) can differ.
- An earlier pass of the same part sent 42, 43, 44 once each, so 42 was the first send.
  - It showed 4 / 12 prompts where 42 differed from 43 = 44 (dev-18, 21, 03, 04).
  - The controlled pass attributes that to cache state, not to the seed.

**Consequence for the S13c seed result (stated plainly).**
- S13c's seed-null cell ran first on each prompt (fresh, then cached sends); its seed-42 cell
  ran after it (all cached).
- So "seed null 4 / 12 vary, seed 42 0 / 12" is **confounded with cache state**. The fixed seed is
  harmless and stays (S1 and S4 alike), but it is not what removed the variation.
- The committed S13c records and docs are not edited. This is recorded here and should go in the
  next session report's carry-forward.

### 2.3 Options for qwen variance (A2)
- **(i) Drop the qwen variance runs as not informative.** Under the fixed sampling rule, qwen
  repeat runs differ only through server cache state. That is reported as a measured
  noise source (2 / 12 prompts here; 8 / 96 first drafts in S13b), not as sampling variance.
  The Gemini variance runs are kept. **Recommended.**
- (ii) qwen variance with seed null. As measured, a null seed does not change greedy decoding
  either. A seed-null run would measure **server nondeterminism (cache state, request order)**,
  not sampling, and it would have to be labelled so.
  - A closer variant, also server noise, would be "cache-cold" runs (model unloaded between
    questions).
  - Neither is sampling variance.
- (iii) Any option that changes temperature for variance runs: **not allowed**. It would be a
  different system from the one whose primary numbers are reported.

### 2.4 Gemini variance
- Seeds 43 and 44, S1 and S4, temperature 1.0, the seed in the request.
- Seeds 43 and 44 go in through the same setting the primary run uses (`DLENS_GEMINI_SEED`) and
  are recorded in `model_identity.request.seed`.
- No determinism is claimed for Gemini.

**How variance is reported** (both models if (ii) is chosen; Gemini only under (i)):
- **Per question:** the spread of the headline F1 over the 3 runs (42, 43, 44): min, max and SD,
  shown as a distribution, plus the share of questions whose M6 "fully correct" flips between any
  two runs.
- **Run to run:** for each pair of runs, the mean per-question F1 difference with a paired
  bootstrap 95% CI (M13: 1,000 resamples, seed 20261019, n ≥ 10).
- **The claim's stability:** the S4 − S1 headline difference computed within each run (3 values),
  each with its paired-bootstrap CI. The claim is "stable" if all three CIs exclude 0.

### 2.5 The 60-question stratification RULE (applied only at the freeze)
No test question is opened or picked now. At the freeze, after `test.jsonl` and its `.sha256`
are signed:
1. **Population:** the 224 test questions **minus Ask** (28; judge- or hand-scored), i.e. 196.
   Ask in or out is an owner sub-decision (row 5).
2. **Strata:**
   - trace: `type` × `hop_bucket` (1, 2-3, 4-5, 6+, plus indirect-only if present);
   - impact: `type` × `hop_bucket`;
   - unanswerable: one stratum.
3. **Allocation:** proportional to stratum size, 60 in total, largest-remainder rounding (ties:
   the larger stratum, then the stratum name). Every stratum with ≥ 1 question gets ≥ 1.
4. **Pick within a stratum:** ascending `sha256("s13d-variance:" + question id)`. It is fixed in
   advance, needs no RNG state, and cannot be steered by reading the questions.
5. The rule text and the resulting id list are hashed into the freeze record (§6).

### 2.6 Quota (Gemini)
- 60 questions × 2 runs × (S1 1 + S4 ~5) = **720 calls** (spec §11.6).
- At 380 usable per day that is ≈ 1.9 quota days.
- Groq's cross-model S4 on the same 60 is separate (spec §9).
- qwen is free.

`Decision:` PENDING (rows 2–5).

---

## 3. S2: long-context stuffing (spec §11.3, §0 row 8)

### 3.1 Definition (proposed)
- **What is stuffed:** every chunk of the S07 index (model SQL chunks, column cards, doc chunks:
  model descriptions and exposures), i.e. **exactly S1's retrieval universe**.
  - Each chunk is rendered by S1's `render_chunk`: id, citation `file:lines`, title, text.
  - Model chunks hold the project's `.sql` source text (the citation basis), not the compiled
    SQL with database prefixes. Spec §11.3 says "all compiled SQL". This is the same code, at
    the line numbers citations use; the raw compiled files cannot be cited by line, so they are
    shown only as a size reference.
  - Column descriptions and types exist only in column cards, so "model + doc" would leave Ask
    questions with less than S1 sees.
- **Ordering:** a content key `(file, line_start, kind, entity)`. Never chunk ids, which are
  hashes, and never retrieval rank.
- **Prompt:** S1's prompt **byte for byte**: `S1_SYSTEM`, `USER_TEMPLATE`, `EVIDENCE_RULE`,
  `S1_DRAFT_SCHEMA`, `REPAIR`, `CLARIFY`. The named-substitution list against S1 is **empty**; only
  the evidence selection differs.
- **Citations:** `S1Ledger` over all stuffed chunks; `chunk_citation` v4 (the same helper,
  `CITATION_RULE`); `build_answer` as S1. Rule 12 holds by construction.
- **Calls:** one answer call, at most one JSON repair (S1's B6), one provider retry. No tools, no
  validator, no linker.
- **Scoring:** the same metrics through `from_s1_record`. S2 records are S1-format: chunk
  citations, no edges, one view.

### 3.2 Token cap: an explicit, recorded exception to the ~3K per-call cap
- **Gemini:** `S2_CAP_GEMINI = 240,000` est. tokens per call (TPM 250K minus 10K for output and
  estimate error).
- **qwen:** the server's context. A prompt is sent only if its est. tokens ≤ 0.95 × (num_ctx −
  1,024).
  - The server is the final judge: Ollama 0.35.1 **rejects** an over-long prompt with
    `exceed_context_size_error` (measured; it does not truncate silently). S2 records that as
    "doesn't fit", never as a refusal by the model.
- `LLMClient(max_input_tokens=S2_CAP)` is built only by the S2 runner. Every other system keeps
  `MAX_INPUT_TOKENS = 3000`.
- The cap, its rule and the provider's num_ctx go in the S2 manifest and in `s2.frozen_hashes()`.
- **The quota counter** counts calls as today (1 per answer, +1 per repair).
- **TPM** gets its own pacing (§3.3), using the same `estimate_tokens` count, which over-counts
  (est. 33,748 vs qwen's real 28,930).

### 3.3 TPM pacing (A4)
- **Why:** `ratelimit.py` limits **requests** per minute only. At 15 RPM × 33.7K = 506K est.
  tokens/min, S2 would pass Gemini's 250K TPM about twice over.
- **Proposed:** a sliding 60-second token window in `LLMClient` (spec order: cap → cache → quota →
  rate limit → send). It waits before a send that would put the window's est. tokens over the
  provider's TPM. Defaults: `gemini` 250,000; others `None` (off).
- **Consequences:**
  - It lives in `src/dlens/agent/llm`, so it **changes `s4.agent_code_sha256()`**, even though it
    must not change S4 or S1 behaviour (their calls are ≤ 3K tokens, 15 × 3K = 45K < 250K, so the
    window never waits).
  - It must land **before 7 Dec**, in its own commit, with `CURRENT_AGENT_SHA` re-pinned and a
    test that S1 and S4 requests and cache keys are byte-identical with and without it.
  - It is listed in the freeze checklist (§6).
  - The cache key must not include it.

### 3.4 Measured: size of the stuffed prompt (offline, `--part s2tokens`)
- **Counter:** `estimate_tokens` (serialised JSON chars / 3, the cap's own counter; it
  over-counts), on S1's prompt with the dev-01 question plus the response schema.
- **Set E:** `corpora/dbt_jira` copied to a scratch `--work` dir and built there with `run_dbt`
  (as `scripts/linker_report.py`). Built and chunked in under 20 s; nothing was written in the
  repo.

| corpus | variant | items | chars | est. tokens |
|---|---|---|---|---|
| synthetic_shop v2 | compiled files (size reference) | 49 | 25,918 | 9,736 |
| synthetic_shop v2 | model chunks | 64 | 27,791 | 10,220 |
| synthetic_shop v2 | model + doc | 115 | 35,384 | 12,838 |
| synthetic_shop v2 | **all chunks (recommended)** | 506 | 95,654 | **33,748** |
| set E (dbt_jira) | compiled files (size reference) | 61 | 165,734 | 58,449 |
| set E (dbt_jira) | model chunks | 347 | 158,667 | 55,171 |
| set E (dbt_jira) | model + doc | 409 | 171,846 | 59,667 |
| set E (dbt_jira) | **all chunks** | 1,311 | 358,621 | **123,917** |

**Real qwen tokens** (from the server's own count below): synthetic all chunks = **28,930**
(est. / real = 1.17).

### 3.5 Measured: does qwen hold it? (local, `--part qwenfit`, owner stop rule A1)

**Ladder.**
- Rungs: 8192 → 16384 → 32768 → 65536, never above 65536.
- 10-minute wall-clock timeout per rung.
- Stop at the first rung that holds the full prompt, or at the first rung with CPU offload
  **and** prompt eval < 50 tok/s.

**Setup.** One send per rung: synthetic all chunks, the dev-01 question, temperature 0, seed 42,
`num_predict` 1024. Model `qwen3:4b-instruct-2507-q4_K_M` (digest `0edcdef34593`), Ollama 0.35.1,
RTX 4050 6 GB.

| num_ctx | result | prompt tokens | prompt tok/s | gen tok/s | size / VRAM (GB) | GPU | valid S2 JSON | wall |
|---|---|---|---|---|---|---|---|---|
| 8192 | rejected: request (28,930 tokens) exceeds the context (8,192) | – | – | – | – | – | – | 3 s |
| 16384 | rejected: exceeds the context (16,384) | – | – | – | – | – | – | 7 s |
| 32768 | **fits**, done_reason `stop` | 28,930 | 620 | **1.3** | 7.64 / 4.10 | **54% (46% CPU)** | yes | 146 s |

- **Verdict:** fits at num_ctx 32768, with CPU offload. Prompt eval at 620 tok/s is above the
  50 tok/s stop line. Generation is slow (1.3 tok/s): about 2.5 minutes per question, ≈ 4 h for
  dev and ≈ 9 h for test, local and free.
- **Server state:**
  - Before: no model loaded (`/api/ps` empty).
  - After: the model was unloaded (`keep_alive 0`), and `/api/ps` was empty again. Nothing was
    reloaded, because nothing was loaded before.
  - The `seeds` part ran later and loaded the model at its default 8192. It was unloaded at the
    end, back to the state at the session start.
- **Proposal:** S2 on qwen at **num_ctx 32768, S2 only**. It is a provider parameter, so it is in
  the cache key and the manifest, and it is listed among S2's frozen settings. S1, S3 and S4 stay
  at 8192.
- **Not proposed:** a server-wide KV-cache quantisation (`OLLAMA_KV_CACHE_TYPE`). It would change
  numerics for every system on the server.
- **Set E on qwen:** 123,917 est. (≈ 106K real at the measured 1.17 ratio) is above the 65,536
  ladder cap. Reported as "doesn't fit on a 6 GB GPU", not run.

### 3.6 Gemini (stated from the measured counts; no call)

| run | calls | est. tokens per call | est. tokens in total | TPM-bound minimum time | RPD 475 | TPD |
|---|---|---|---|---|---|---|
| S2 test (synthetic) | 224 (+ ≤ 224 repairs, worst case) | 33,748 | **7.56M** (6.48M at the qwen count) | 7 calls/min → ≥ 32 min | 1 day (2 worst case) | **owner TODO (row 10)**: days = ⌈7.56M / TPD⌉ |
| S2 set E | 60 | 123,917 | **7.44M** | 2 calls/min → ≥ 30 min | same day if under the daily budget | days = ⌈7.44M / TPD⌉ |
| both | 284 | – | **15.0M** | ≥ 62 min | 1 day (the dev budget 400, stop at 380) | days = ⌈15.0M / TPD⌉ |

- Both prompts fit the 250K TPM per call.
- No TPD is assumed: the owner reads the AI Studio rate-limit page (row 10).
- Gemini's tokenizer differs from qwen's; the estimate over-counts both.

### 3.7 Frozen hashes for S2 (like `s1.frozen_hashes`)

**Reused from S1, and asserted equal to S1's values in a test:** `system`, `user_template`,
`evidence_rule`, `schema`, `repair`, `clarification`, `citation_rule`.

**S2's own:**
- `corpus_rule`: "all S07 index chunks (model, column, doc)";
- `ordering_rule`: "(file, line_start, kind, entity)";
- `cap_rule`: the §3.2 text, with `S2_CAP_GEMINI` and the qwen rule;
- `num_ctx_rule`: "qwen num_ctx 32768 for S2 only";
- `budget_rule`: one answer + one repair + one retry.

**The manifest also records:** the stuffed prompt's est. tokens and its sha256 (corpus-level,
without the question), the index key (chunker version, embedder revision), `model_identity` and
`quota`.

### 3.8 Quota
- **S2 test:** 224 calls (spec §11.6).
- **Set E:** + 60 if row 9 is approved.
- **Dev:** a qwen S2 dev run in S16 (free, ≈ 4 h). Gemini S2 on dev only with an owner quota plan
  (96 calls, ≈ 3.2M est. tokens).

`Decision:` PENDING (rows 6–11).

---

## 4. S3: agent with graph tools only (ablation of S4)

### 4.1 What one switch already does (read from the code)
`Toolbox(graph, project_dir, index=None)` turns off three components together, and no others:
- the **`search_docs` tool**: `Toolbox.has_docs` is False, so `specs()` omits it and
  `prompts.tool_system(False)` omits `SEARCH_DOCS_STEP`;
- the **linker's hybrid stage**: `entity.link(..., index=None)` runs stages 1–2 only and records
  `hybrid: unavailable`;
- the **F6 code docs step**: `Agent._docs_gate` returns False without an index.

`eval/systems/s4.py --no-hybrid` already runs exactly this.

### 4.2 Each S4 component: keep or drop (owner decisions, rows 12–17)

| S4 component | reads the index? | proposed for S3 | what S4 − S3 then isolates |
|---|---|---|---|
| `search_docs` tool (LLM-chosen) | yes | **drop** | docs and SQL text retrieval for the agent |
| F6 code docs step (`docs_evidence`) | yes | **drop** | the same, chosen by code (Ask "no lineage evidence" cases) |
| linker hybrid stage (stage 3, dense over column cards) | yes | **drop** (stages 1–2 only) | paraphrase linking by retrieval |
| validator (R1–R9, R2r, R8c, regenerate, salvage) | no | **keep** | – (not isolated; the no-validator ablation is S4-raw, spec §11.5) |
| coverage completion G1 (augmented view) | no | **keep** | – |
| code steps: chain trace, R9 reachability fact, unknown-column refusal, ambiguity policy (chain / per candidate / clarification), code evidence, linked evidence, candidate trace | no | **keep** | – |
| answer prompt, draft schema, budget rule (8 calls, ≤ 5 tool-phase, `REGENERATE_RESERVE`), cache | – | **keep, identical** | – |

**Recommended definition:**
- S3 = S4 with `index=None`;
- **S4 − S3 = retrieval's contribution** (docs evidence plus the hybrid linker), with the
  validator, code steps and views held equal;
- S3 is reported three ways like S4 (S3-raw, S3-validated, S3-augmented).

**Alternatives:**
- Keep the hybrid stage and drop only the docs. That isolates docs retrieval alone, but S3 would
  then still use dense retrieval, so it is not "graph tools only".
- Drop the validator too. That mixes two ablations; S4-raw already covers the validator for free.

**Pairing:** the S0-linked row paired with S3 is the **hybrid-off** S0-linked (M14: the same
linker configuration), so S0-linked(off) − S3 = LLM loss without retrieval.

### 4.3 Named substitutions against S4 (in the style of A1's `ALLOWED_DIFFERENCES`)
1. `tool_system`: `prompts.tool_system(False)` instead of `tool_system(True)` (no
   `SEARCH_DOCS_STEP`).
2. `tool_specs`: the specs without `search_docs`.

Every other `prompt_hashes()` key (`answer_system`, `draft_schema`, `answer_repair`,
`tool_repair`, `regenerate`, `directives`) and `tool_settings()` must equal S4's. A test asserts
that exactly these two keys differ.

`agent_code_sha256` is S4's **by construction** (same code). The S3 manifest records it,
`hybrid: false`, `index_status: "S3: no index (graph tools only)"` and its own system label
`s3-<model>`.

### 4.4 Measured: where S3's inputs certainly differ from S4's (offline, `--part s3`)

| S4 records | search_docs (LLM) | search_docs (code F6) | hybrid stage ran | hybrid top-1 | union |
|---|---|---|---|---|---|
| qwen pilot | 8 | 0 | 9 | 5 | 17 / 96 |
| Gemini pilot | 22 | 0 | 8 | 5 | 26 / 96 |
| qwen post-S13c | 8 | 5 | 5 | 2 | 18 / 96 |

- qwen post-S13c union: dev-21, 27, 28, 37, 41, 51, 57, 62, 63, 66, 78, 80, 82, 84, 85, 86, 94, 95.
- Other questions can still differ, because the tool prompt has no search_docs step and the model
  may choose other calls.

### 4.5 Dev plan and quota
- **Runner (S16):** `eval/systems/s3.py`, a thin wrapper that builds S4's agent with `index=None`,
  with its own label, prefix and manifest. No agent code change.
- **Dev:** an S3 dev run on local qwen only (free), as a diagnostic (`eval/runs/s3/diagnostic/`).
  Gemini S3 dev only if the owner approves a quota plan later (≈ 96 × 4 ≈ 384 calls, 1 day).
- **Test quota:** ≈ 4 calls × 224 = **896 Gemini calls** (spec §11.6; ≈ 2.4 quota days). If
  quota is cut, spec §11.6's cut order applies: S3 drops to the 60-question subset third.

`Decision:` PENDING (rows 12–17).

---

## 5. C1: DLens engine vs dbt-colibri on the gold spec (short)

- **Package:** `dbt-colibri` **0.3.7** (PyPI, uploaded 5 Oct 2026; read-only check of the PyPI
  JSON, 23 Oct 2026).
  - Licence **MIT**.
  - `requires_python >= 3.9`; depends on `click >= 8.1.7` and `sqlglot[c] >= 30.0.0`; brings no
    dbt.
  - Source `github.com/b-ned/dbt-colibri`. Pin exactly `==0.3.7`.
- **Install isolated, never in `uv.lock`.** Its sqlglot floor would conflict with our pin
  (30.21.0). Use `uv tool run` / a throwaway venv and record the resolved sqlglot version in the
  C1 report.
- **How its edges are read:**
  - `colibri generate --manifest <target>/manifest.json --catalog <target>/catalog.json
    --output-dir <scratch>` writes `colibri-manifest.json` plus an HTML dashboard.
  - The JSON's column-edge keys are **not documented** in its README. Step 1 of C1 inspects the
    file on synthetic_shop and writes a small reader (`eval/systems/c1.py`) for the exact
    pinned version.
- **Mapping to gold ids:**
  - colibri's node ids go through the M2 normalisation (short id `model.column`, case-folded,
    quotes stripped; fully-qualified relation names mapped to the model through the dbt
    manifest's `relation_name`).
  - Seeds and sources follow the same rule as the gold spec.
  - Unmapped ids are counted and listed, never dropped silently.
- **Metric (no LLM):** edge precision, recall and F1 against `lineage_spec.yml`, computed the same
  way for DLens and colibri.
  - **direct** edges (gold `phase: v0.1`), as (from, to) pairs;
  - **indirect** (gold `phase: v0.3`) only if colibri emits typed or filter/join edges; otherwise
    stated "colibri emits no indirect edges";
  - optionally kind accuracy on the matched direct edges, if colibri types them.
- **Independence caveat:** colibri is also sqlglot-based, so C1 shows wrapper-level differences,
  not a fully independent parser. The perturbation oracle stays the independent check.
- **No freeze dependency:** C1 never touches questions, prompts or models.
- **Commands for later (not run in this session):**
  ```
  uv tool run --from dbt-colibri==0.3.7 colibri --help
  uv tool run --from dbt-colibri==0.3.7 colibri generate \
    --manifest corpora/synthetic_shop/target/manifest.json \
    --catalog corpora/synthetic_shop/target/catalog.json --output-dir <scratch>/colibri
  uv tool run --from dbt-colibri==0.3.7 python -c "import sqlglot; print(sqlglot.__version__)"
  ```

`Decision:` PENDING (row 18).

---

## 6. Freeze checklist draft (7 Dec 2026)

Status: **exists** = recorded in today's manifests or code; **to build** = needs this design's
decisions or a later session.

| item | S0 | S1 | S2 | S3 | S4 | status |
|---|---|---|---|---|---|---|
| prompt / text hashes | – | `s1.frozen_hashes()` (8 keys) | `s2.frozen_hashes()` (§3.7) | `prompt_hashes(toolbox)` | `prompt_hashes(toolbox)` | S1, S4 exist; S2, S3 to build |
| schema hash | – | in `frozen_hashes` | = S1's | `draft_schema` | `draft_schema` | exists (S2, S3 by reuse) |
| cap / budget rule | depth 50 | `budget_rule`, cap 3000 | `cap_rule`, `S2_CAP_GEMINI`, qwen rule | `tool_settings()` | `tool_settings()` | S2 to build |
| agent / system code sha | `s0.py` in git commit | git commit | git commit | `agent_code_sha256` (= S4's) | `agent_code_sha256` | exists; re-pinned once after TPM pacing |
| TPM pacing landed (A4) | – | must not change requests | used | must not change requests | must not change requests | **to build, before 7 Dec**, with the byte-identical test |
| validator version | – | – | – | in agent sha | in agent sha | exists |
| linker configuration | hybrid flag | – | – | hybrid off | hybrid on | exists |
| model ids | – | `gemini-3.5-flash-lite`, `qwen3:4b-instruct-2507-q4_K_M` | same | same | same | exists |
| Ollama digest + server version | – | `model_identity` (digest `0edcdef34593…`, 0.35.1) | same | same | same | exists |
| sampling | – | temp 0 / seed 42 (qwen); temp 1.0 / seed 42 (Gemini) | same | same | same | exists |
| num_ctx | – | 8192 | **32768 (qwen, S2 only)** | 8192 | 8192 | S2 to build |
| Gemini request (temperature, thinking config) | – | `model_identity.request` | same | same | same | exists |
| index key (chunker version, embedder revision) | – | manifest `index_key` | same | none (no index) | manifest `index_key` | exists |
| metrics versions | design 1.2 / metrics 1.3.0 in each manifest | | | | | exists (changes only if row 1 = (b)) |
| variance seeds | – | 43, 44 (Gemini; qwen per row 3) | – | – | 43, 44 | to build (decision) |
| 60-question rule + id list hash | – | applies | – | – | applies | to build at the freeze (§2.5) |
| test + set-E question hashes | | | | | | **to build:** `test.jsonl`, `external.jsonl` and their `.sha256` files do not exist yet (S15a drafts, Buffer A review) |
| judge (Ask): model id, prompt hash, calibration κ ≥ 0.6 on 30 labels | | | | | | to build (S16) |
| S0 reference | versioned baseline `eval/runs/s0/baseline/s13c/` | | | | | exists |
| corpus pins | synthetic_shop `v1_frozen.sha256`; dbt_jira pinned commit `0ed5dcf2…` (SOURCE.md) | | | | | exists |
| server settings for local runs | `OLLAMA_NUM_PARALLEL` 1, keep-alive (session reports only) | | | | | to add to the manifest (cache-state effect, §2.2) |

---

## 7. Order of work after the decisions

| session | content | needs from the owner |
|---|---|---|
| **S14** | E2 `dlens ui --project`, E4b public-project coverage | screenshot review (visual changes) |
| **S15a** | D5b: 224 test + 60 set-E question drafts (not opened by anyone but the review) | review all 284 in Buffer A (30 Nov – 6 Dec); sign the freeze |
| **S16** | TPM pacing in `LLMClient` (own commit, sha re-pin, byte-identical test) → `eval/systems/s2.py` + `s3.py` (frozen hashes, tests) → qwen S2 and S3 dev diagnostics (local) → Ask judge plumbing (OpenAI-compatible adapter, judge prompt, the 30-label calibration harness) → M7 split columns in the report scripts (if row 1 = (a)) → C1 reader + edge F1 (if row 18 = go) | these decisions; the TPD reading (row 10); a quota plan before any Gemini S2 / S3 dev check; 30 Ask calibration labels |
| **S15b** | v0.3.0 release: demo bundle rebuild + presets (local), docs, explain gate, tag | the explain gate; approve the tag |

- **Dates:** S14, S15a and S16 before **29 Nov** (v0.3.0); S15b by 29 Nov; Buffer A review; the
  freeze on **Mon 7 Dec**.
- S16 must finish before the freeze, because S2 and S3 are hashed then.
- If S16 slips, the spec §11.6 cut order applies, and S2 / S3 are run after the freeze only from
  the code frozen on 7 Dec.

---

## Change log

- 23 Oct 2026: v0.1. Design only, every Decision PENDING. Measurements:
  - **M7 split:** S1 qwen 0.533 overall, 0.886 on dotted-claim citations, 0.000 on 34 no-column
    answers. Under (b): S1 qwen 0.533 → 0.967, S4 qwen validated 0.899 → 0.986. Under (c):
    S4 qwen loses 8 / 267 claims, 4 answers emptied.
  - **S3:** S4's index-dependent components touch 17 / 26 / 18 dev questions.
  - **S2:** synthetic all chunks 33,748 est. (28,930 real qwen) tokens; set E 123,917 est.
  - **qwen S2:** fits at num_ctx 32768 (54% GPU, 1.3 tok/s generation, 146 s).
  - **Seeds:** a different seed changed 0 / 12 qwen outputs at temperature 0; cache state changed
    2 / 12. The S13c seed result is confounded with cache state.
  - **dbt-colibri:** 0.3.7, MIT.
