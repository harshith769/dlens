# S13c design: F1 option (d), F6 gate, linker items, adapters, seed (before the 7 Dec freeze)

**Version:** 0.1 (22 Oct 2026). **Status:** decided by the owner, 22 Oct 2026 (below). Implementation in the order A1 → A2 → L2 →
L1 → (F6 re-measure) → F1 (d1) → F6 → S.
**Branch:** `s13-gates-linker` (matches CI's `s[0-9][0-9]-*`).
**Inputs:** `docs/plans/post-pilot-fixes.md` (F1 option (d), F6 next design),
`eval/reports/s13b_session.md` (carry-forward), `eval/reports/s13b/diagnosis.md`,
`docs/plans/linker-design.md`, `eval/reports/linker.md`, `eval/reports/s12b_session.md`
(hybrid on/off), `docs/explain/retrieval.md` (citation helper), ADR 0026 (A5 allowlist), ADR 0029.
**Measurements:** `scripts/s13c_measure.py` (read-only; parts `f1`, `f6`, `linker` offline, no
LLM; part `seed` sends prompts to the **local** Ollama model only). Every number below comes
from it and is labelled as dev, offline or local.

Rules that hold throughout:
- No cloud call; never `--allow-cloud`; never read `.env`.
- `eval/questions/test.jsonl`, `external.jsonl` and their `.sha256` files are not opened.
- `eval/metrics.py` 1.3.0 and metrics-design v1.2: no edits.
- The lineage engine (`src/dlens/lineage`) is not changed.
- Committed pilot and diagnostic records are never rewritten.
- **Linker-test is never used to choose a rule** (linker-design §3.4, §6). Its numbers are
  reported, separately.
- **Every rule below was written after seeing dev cases.** Each is recorded as such, and the
  honest check is the test set after the 7 Dec 2026 freeze. Unit tests pin mechanisms, not
  scores.
- **S1 symmetry (rule 12) and the B8 freeze.** `s1.frozen_hashes()` covers S1's prompts,
  schema, citation rule and budget rule. It does **not** cover chunk ids, index ordering or
  Ollama options. Items L3 (chunker) and S (seed) change what S1 runs on, so each is an explicit
  owner decision, recorded in the S1 design change log, and applied to S1 and S4 alike.

## Decision list (owner, at the S13c STOP)

| # | item | options | recommendation | one-line reason |
|---|---|---|---|---|
| 1 | F1 option (d) | (d1) tool provenance / (d2) question wording / defer | **(d1) + derivation-wording guard** | Recovers 37 / 55 consistent R8 drops on dev, 0 inconsistent, 0 trace; follows the ADR 0026 per-tool allowlist |
| 2 | F6 gate | two-condition gate / threshold / defer | **two-condition gate** | Separates all 11 fixtures with existing linker constants only; no new threshold |
| 3 | L1 "column in model" | `qualified` tier / defer | **`qualified` tier** | One rule fixes the dev-29/40/56/71 and dev-75 hybrid ties |
| 4 | L2 dotted unknown model | no hybrid for it / defer | **no hybrid** | dev-93 stops being a clarification; the same check as gate condition 1 |
| 5 | L3 chunker + tie-break | do with acceptance STOP / defer to v1.0 | **do, with the acceptance gate** | Ids stop deciding ranks; 235 / 506 ids move, so S1's retrieval must be shown unchanged first |
| 6 | L4 dev-15 | no change / retrieval rule | **no change** | It is S1's retrieval; a fix would move the frozen baseline on one dev case |
| 7 | L5 "exchange rate" | – | **no rule (linker-test case)** | linker-design §6 |
| 8 | A1 openai_compat `__context__` | fix / keep | **fix** | The F5 pattern; a sentinel test |
| 9 | A2 ollama connection errors | (a) retryable / (b) fail fast | **(a)** | Align with F5; one free local retry |
| 10 | S seed | (a) fixed seed S1+S4 / (b) keep null / (c) qwen only | **(a) seed 42, both systems, Ollama and Gemini** | Seed null: 4 / 12 identical prompts vary over 5 sends; seed 42: 0 / 12 (local, small sample) |

---

## F1 option (d): R8c completion over indirect edges, under the family allowlist

**Problem (S13b step 0).** Of 55 gold-consistent R8-failed claims (both models, both rounds), the
dev-53, dev-65, dev-60, dev-69, dev-71 and dev-07 / dev-59 claims join their columns only through
indirect (JOIN / FILTER) edges. R8c never bridges indirect edges (s12-design A5). Options (a)–(c)
recovered at most 1 of 55.

**The allowlist, and where it comes from.** ADR 0026 fixed the traversal per tool:
`trace_upstream` direct only, `impact_downstream` direct + indirect. Two ways to tie R8c to it:
- **(d1) Tool provenance (recommended).** An indirect ledger edge may bridge only if an
  `impact_downstream` result showed it, i.e. the tool whose allowlist includes indirect edges.
  It needs no question classifier. Note that the loop's impact wording rule
  (`_IMPACT_WORDING`) misses "depends on" and "uses … further down" (dev-71, dev-66), so a
  wording-based family would miss real impact questions.
- (d2) Question wording (`loop._intent_tool`). Rejected for the reason above, and because the
  validator would then classify questions.

**Guards (all kept, plus one new):**
1. Anchor: a cited edge touches a named column (unchanged; an indirect cited edge counts, as
   today).
2. Directed shortest bridge between named columns, ≤ `MAX_COMPLETION_HOPS` = 4 (unchanged; no
   measured bridge needs more). Siblings that only share a descendant stay unconnected.
3. "direct" / "directly" forbids any bridge longer than one hop (unchanged).
4. **New: no indirect bridge for derivation wording.** If the claim says derived / comes from /
   computed / calculated / sourced / originates / aggregated / renamed / identity / copied /
   passed through, only direct edges may bridge. A JOIN path never makes "Y is derived from X"
   true. On dev this guard changes nothing (no passing claim uses such words); it is a safety
   guard, pinned by a negative test.
5. Completed indirect edges are ordinary cited edges afterwards: R3 checks them by kind (A5),
   and R5 fails "aggregated" over a JOIN edge (no indirect kind is in `KIND_WORDS`).

**Measured (dev, offline, both pilot records, the S13b validator plus (d1)):**

| variant | gold-consistent claims passing | not consistent passing | trace-family claims changed |
|---|---|---|---|
| today (S13b) | 0 / 55 | 0 / 3 | – |
| (d1) tool provenance | **37 / 55** | 0 / 3 | 0 |
| (d1) + derivation-wording guard | **37 / 55** | 0 / 3 | 0 |

- Recovered: qwen dev-53 ×8 (both rounds) and dev-65 ×4 (first round); Gemini dev-07, dev-59,
  dev-60 ×6, dev-69 ×3 and dev-71 ×14.
- Still failing, as they should:
  - dev-57: chunk-only citations, no anchor.
  - dev-65 second round: siblings in one model, no directed path.
  - dev-72 #0: a 5-hop direct bridge; F1 (a) is not proposed.
  - dev-72 #1: "directly".
  - dev-75: no path.
  - Gemini dev-68 / dev-59 #2 / dev-05 / dev-38: compound sibling claims.

**Files.** `src/dlens/agent/validator.py` (`_ledger_adjacency`, `_complete_one`),
`docs/explain/validator.md`. Rule-9 touch: **validator**.
**Tests (written before code).**
- Positive: dev-53 ×4 and dev-71 cases (Gemini record) complete with indirect edges and pass.
- Negatives:
  - the same dev-53 claim with "is derived from" wording still fails R8;
  - an indirect edge that only a `trace_upstream` / `get_model_sql` path showed (synthetic
    ledger) never bridges;
  - a "directly" claim over an indirect 2-hop bridge fails;
  - the sibling case still fails;
  - "aggregated" over a completed JOIN edge fails R5.
- The B3 outcome snapshot is unchanged: no existing test has indirect impact edges in a
  multi-column claim (to be confirmed by the A3-style in-process run before code).

`Decision:` **APPROVED (d1) + derivation-wording guard** (owner, 22 Oct 2026), as designed.

---

## F6 gate: the code `search_docs` step only when the question names something known

**Problem (S13b).** qwen ends 11 dev questions with "no lineage evidence": 5 Ask, dev-41,
dev-66 and dev-93–96 (unanswerable). An ungated code `search_docs` step would turn the 4 correct
refusals into docs-based answer phases (search_docs has no score threshold).

**Gate signals measured (offline, the question text, existing linker only):**

| signal | Ask / lineage that should pass | unanswerable that must block |
|---|---|---|
| linker stages 1–2 on the whole question (no hybrid) | none match (0 / 7) | none |
| linker with hybrid (existing `COS_MIN` 0.695, tau 0.6) | dev-66, 78, 82, 84, 86 match; dev-41, 87 don't | dev-94, 95, 96 none; **dev-93 matches** (`fct_orders.refunded_amount` 0.81) |
| a dotted `a.b` whose model `a` is not a model / seed / source | – | dev-93 (`fct_returns`), dev-96 (`payroll`) |

**Proposed gate (a non-threshold rule; existing linker constants only, no new value):** the
code step runs only when the tool phase ended with no lineage evidence, an index exists, **and**
both of these hold:
1. no dotted `a.b` in the question names an unknown model (unknown → the existing refusal
   path); and
2. the linker (hybrid on, as S4 runs it) returns ≥ 1 candidate for the question text.

The step then calls `search_docs` with the question as a recorded `code` step (rule
`docs_evidence`), and the answer phase runs on its hits.

**Effect on the fixtures (dev, offline, gate only; the answers themselves are not predicted):**
- runs for dev-66, dev-78, dev-82, dev-84, dev-86;
- stays refused for dev-41, dev-87 (no linker candidate; refused today too, no change) and for
  **all four unanswerables** dev-93–96.

No threshold is needed, so the threshold branch is not proposed.

**Guards.**
- No index → unchanged refusal.
- Lineage evidence present → the step never runs.
- dev-19 and dev-89–92 refuse before this point (unknown column, no LLM call).
- Chunk-only lineage claims still fail R8 (S12b B4).
- The answer-phase budget must keep the A6 reserve (278): the largest added evidence size is
  measured in the implementation step, with a STOP if any prompt would trim.

**Files.** `src/dlens/agent/loop.py` (the tool phase's end, `_answer_phase`),
`docs/explain/agent.md`. Rule-9 touch: **loop**.
**Tests.** The 5 qwen Ask refusals and dev-93–96 as fixtures (their recorded tool phases, a stub
model for the answer):
- dev-66 / 78 / 82 / 84 / 86 run the code step;
- dev-41 / 87 / 93–96 don't;
- no index → no step;
- a lineage question with evidence → no step.

`Decision:` **APPROVED, the two-condition gate** (owner, 22 Oct 2026). Condition: after the L2 and L1
commits and before any F6 code, `scripts/s13c_measure.py --part f6` is re-run on the new linker.
All 11 fixtures must keep the same split (run: dev-66, 78, 82, 84, 86; stay refused: dev-41,
87, 93–96). If any flips: STOP and report. The A6 budget STOP stays as written.

---

## Linker items (the linker is unfrozen after the pilot)

All linker numbers are on linker-dev and the dev mentions; linker-test is reported, never used
to choose. The linker feeds S0-linked and S4 (S1 does not use it).

### L1. "column in model" (fixes the hybrid ties on dev-29, dev-40, dev-56, dev-71, dev-75)

**Measured (dev mentions, offline):** the mention names a column and its model in words, and
stage 2 scores the exact column only `fuzzy` (≈ 0.66–0.68, because "in <model>" counts as extra
tokens). So it is not "confident", stage 3 (hybrid) runs, and hybrid ranks same-model siblings
above it:

| mention | hybrid off (top) | hybrid on (top 3) |
|---|---|---|
| line_margin in int_order_item_margins | line_margin fuzzy 0.675 | line_amount 0.856, quantity 0.851, **line_margin 0.843** (ambiguous) |
| order_id in int_order_profit | order_id fuzzy 0.658 | customer_id 0.860, **order_id 0.835** |
| revenue_marketing in fct_daily_revenue | revenue_marketing fuzzy 0.682 | order_count 0.854, order_date 0.852, **revenue_marketing 0.840** |
| customer_id in int_customer_sessions | customer_id fuzzy 0.653 (ties stg/int web sessions) | customer_id 0.835, session_count 0.823 |
| customer segment in customer leaderboard (dev-75) | customer_segment fuzzy 0.675 | full_name 0.852, **customer_segment 0.840** |

**Proposed: a `qualified` stage-2 tier.** When the text splits at a phrase boundary ("in", "of",
"from") into a column part and a model part, and:
- the column part matches a column name at the surface or rewritten tier, **and**
- the model part equals that column's model name (all tokens, layer prefix included), or its
  name without the layer prefix when that is unique,

then the candidate gets tier `qualified`, base = `SURFACE` (0.93). It is then "confident", so the
hybrid stage does not run. "last name in raw customers" names the layer, so it picks
`raw_customers.last_name`, not `stg_customers` (the dev-75 tie; B6 settled it in the loop, and
now the linker settles it too).

`Decision:` **APPROVED, the `qualified` tier** (owner, 22 Oct 2026), plus these negative tests:
- "number of orders per customer" is not qualified (dev-15 still links to
  `dim_customers.order_count`);
- "revenue from fct_orders to dim_customers" gives no qualified candidate from a multi-model
  phrase;
- "orders in the last month" gives no qualified candidate;
- a model part that matches only the unprefixed name when that name is **not** unique (e.g.
  "order_id in orders") is not qualified.

Linker-dev is reported before and after; linker-test separately, and no rule is ever adjusted in
response to it.

**Tests.** The five mentions above give a unique top-1 (not ambiguous). "line_margin in
fct_orders" (wrong model) is not `qualified`. Bare "line_margin" is unchanged. The linker-dev
report rerun is checked for regressions, and linker-test is reported.

### L2. A dotted name with an unknown model never goes to hybrid (dev-93)

`fct_returns.return_amount` matches `_DOTTED`, but `dotted_column` returns None for an unknown
model. The text then falls through to stages 1–3, and hybrid ties three `refunded_amount`
columns, so S0-linked / S4 return a clarification for an unanswerable question.

**Proposed:** a dotted `a.b` whose model `a` is not a model, seed or source returns no candidates,
with `closest` set to the nearest model names. It never runs stage 3. dev-93 then refuses
(refusal accuracy for S0-linked hybrid on: the 0.889 of S12b goes back toward 1.000; to be
measured, not predicted). This is the same check as the F6 gate's condition 1, in one place.

### L3. Citation-helper rules into the chunker, and rank tie-breaking independent of chunk ids

`chunk_citation` fixes seed cards (line 1), YAML descriptions (`- name:` through the description)
and star cards (`level: star`) **after** chunking, because chunk ids hash the line range.
**Measured (offline, the synthetic_shop index, 506 chunks):** 235 chunks would change range (186
column cards, 49 docs), so their ids change, and 19 change level only.

**Proposed, in two parts, tie-breaking first:**
1. BM25, dense and RRF break score ties by a content key, `(file, line_start, kind, entity)`, not
   by chunk id or row order.
2. The chunker emits the corrected ranges, and `chunk_citation` becomes the identity on them.

**Acceptance (before anything else changes):**
- S1's dev retrieval (the shown chunks for all 96 dev questions, compared by content key, not
  by id) is identical before and after.
- The linker report on linker-dev is identical.
- The engine-agreement test (19 / 19 star cards) still passes.

If any shown chunk differs, STOP. The pinned chunk-id-list sha (S12a A3 test) must be re-pinned:
an edit to an existing test, owner approval needed. S1: a B8 change-log line (no `frozen_hashes`
change). The demo bundle and presets are rebuilt in S15 anyway.

Recommendation (v0.1): do it, with the acceptance gate; if S1's retrieval moves, defer to v1.0.

`Decision:` **DEFERRED to after v1.0 (both parts)** (owner, 22 Oct 2026).
- Reason: no user-visible change. `chunk_citation` already corrects citations, and with stable
  ids, tie-breaking by id is stable.
- It would also change S1's retrieval inputs before the freeze (rule 11).
- The full design and measurements stay here. Moved to "Later" in the carry-forward.

### L4. dev-15 ("number of orders per customer")

The linker already gets it right: `dim_customers.order_count` 0.94, not ambiguous; S4 answers it on
both models. The miss is S1's **retrieval** (the card is outside the top 5 for BM25, dense and
hybrid; S1 Gemini refused). Fixing retrieval for it would move the frozen baseline on a single
dev case.
`Decision:` **APPROVED: no change** (owner, 22 Oct 2026). A known paraphrase limit of the retrieval baseline.

### L5. "exchange rate"

This is `lk-no_match-016`, a **linker-test** case (gold: no match). Hybrid returns
`stg_payments.amount_usd` 0.650 above tau. By linker-design §6 a linker-test case is never a
target. **No rule is proposed for it.** L1–L2 are checked for whether they change it, and that is
reported.

`Decision:` **APPROVED: no rule** (owner, 22 Oct 2026). The session report states whether L1 / L2 change
`lk-no_match-016`.

---

## Adapters

### A1. `openai_compat.py`: no httpx request on `__context__`
It raises `ProviderError(...) from None` inside `except httpx.HTTPError`, so `__context__` still
holds the httpx error and its request (`Authorization` header). The fix is the F5 pattern: build
the error in the `except` block and raise it after. A sentinel-key test checks every text form
plus `__cause__` and `__context__`. Behaviour (messages, retryable) is unchanged.
`Decision:` **APPROVED: fix** (owner, 22 Oct 2026), with a sentinel test (text forms, `__cause__`, `__context__`).

### A2. `ollama.py`: connection errors
Today any exception becomes a `ProviderError` with `status_code` None, so `retryable` is False:
a dropped local connection (Ollama restarted, a model reload timeout) is never retried.
- **(a) Align with F5:** `httpx.TransportError` / `ConnectionError` → `retryable=True`
  (one retry, no quota at stake). `ollama.ResponseError` keeps its status mapping.
- (b) Keep: a local server that is down stays down, so fail fast.

Raise after the `except` block either way (no key, but the same pattern).
`Decision:` **APPROVED (a) retryable** (owner, 22 Oct 2026), raised after the `except` block.

---

## S. Seed (S1 and S4 alike)

**Observation (S13b diagnostic).** At temperature 0 with no seed, 8 of 96 qwen first drafts
(dev-17–28) differed from the pilot's, with identical evidence and prompts.

**Protocol (owner, stated before the run).**
- **Questions:** the 8 questions whose first drafts differed (dev-17, 18, 20, 21, 22, 24, 27, 28),
  plus 4 controls by a rule fixed in advance: the 4 lowest dev ids among the 88 unchanged drafts
  (dev-01, dev-02, dev-03, dev-04).
- **Prompts:** each answer-phase prompt is built **once** from the record's tool calls, saved to
  a scratch file outside `eval/runs`, and that saved prompt is sent unchanged.
- **Sends:** 5 with seed null, then 5 with seed 42, temperature 0, `num_ctx` 8192, model
  `qwen3:4b-instruct-2507-q4_K_M` (digest `0edcdef34593`), strictly one request at a time.
- **Comparison:** outputs are compared **with each other only**.
- **Server state:**
  - The Ollama server log shows `OLLAMA_NUM_PARALLEL:1` and `OLLAMA_KEEP_ALIVE:5m0s`: no
    parallel batching.
  - The model was loaded (`/api/ps`) before every cell.
  - Ollama 0.35.1, local GPU (RTX 4050).

Command (local only; no cloud):

```
uv run --extra agent --extra retrieval python scripts/s13c_measure.py --part seed --reps 5 \
  --save-dir <scratch dir>/seed_prompts
```

**Result (local, 22 Oct 2026):**

| id | group | seed null: distinct / 5 | seed 42: distinct / 5 |
|---|---|---|---|
| dev-17 | differed | 1 | 1 |
| dev-18 | differed | 1 | 1 |
| dev-20 | differed | 1 | 1 |
| dev-21 | differed | 1 | 1 |
| dev-22 | differed | 1 | 1 |
| dev-24 | differed | 1 | 1 |
| dev-27 | differed | 2 | 1 |
| dev-28 | differed | 1 | 1 |
| dev-01 | control | 1 | 1 |
| dev-02 | control | 2 | 1 |
| dev-03 | control | 2 | 1 |
| dev-04 | control | 2 | 1 |

- **Seed null:** 4 of 12 prompts gave 2 different outputs over 5 identical sends: dev-27, and
  the controls dev-02, dev-03 and dev-04.
- **Seed 42:** 12 of 12 gave a single output.

So temperature 0 alone is not deterministic on this server, even with one request at a time and
the model resident. The variation hits unchanged questions as often as the 8 that differed, so
the S13b diagnostic's 8 differing drafts are this sampling variation, not a fix effect. A fixed
seed removed it in this sample (12 prompts × 5 sends: small, stated as such).

**Dropped as inconclusive:** an earlier version compared reconstructed prompts' outputs with the
pilot and diagnostic drafts. The records do not store the sent prompt text, so a mismatch could
not be told apart from a reconstruction difference. Not used.

**Options.**
- **(a) Fixed seed for S1 and S4 alike (recommended).**
  - Ollama `options.seed = 42` in the provider defaults. Both systems use the same adapter, so
    the symmetry holds by construction.
  - The manifests' `model_identity.sampling` already records `seed`.
  - It changes the provider `params`, so every cache key moves once, for both systems: future
    runs are uncached once.
  - S1: a B8 change-log line. `frozen_hashes` does not cover sampling, so no hash moves.
  - Gemini: the API has a `seed` field, but determinism is best effort at temperature 1.0 and it
    cannot be checked here (no cloud call). Proposed: send the same seed, record it, and claim
    nothing about Gemini determinism.
- (b) Keep seed null and report run-to-run variation as noise (measured above: 4 / 12 prompts
  vary).
- (c) Seed for qwen only. Rejected: rule 12 asks for one sampling rule per model across S1 and
  S4. That holds either way, but (a) also covers the Gemini panel.

**Files.** `src/dlens/agent/llm/ollama.py` (default options), `src/dlens/agent/llm/gemini.py`
(seed in the config, if (a) includes Gemini), `docs/explain/llm.md`, `docs/plans/s1-design.md`
(B8 change log). Tests:
- the request carries `seed: 42` for both systems;
- the manifest records it;
- the cache key differs from seed null.

`Decision:` **APPROVED: seed 42 for Ollama, S1 and S4 alike** (owner, 22 Oct 2026), with a B8 change-log line in
`s1-design.md`.
- **Gemini:** the seed field is implemented behind a manifest-recorded setting, **off by
  default**. No determinism claim.
- A one-call smoke command (seed 42, `--allow-cloud`, `GEMINI_DAILY_BUDGET=475`, printing only
  the HTTP status / `ProviderError` class) is prepared for the owner, **not run**.
- If it succeeds, turning the Gemini seed on is one commit with a test. If it fails, the Gemini
  seed stays off, and that is recorded.

---

## Order of work after the decisions (one commit per item, smallest blast radius first)

A1 → A2 → L2 → L1 → F1 (d) → F6 gate → L3 (with its acceptance STOP) → S (seed, symmetric).
Each commit:
- changes only the files named;
- adds the tests written here first;
- updates the named `docs/explain/*.md` with a "changed in S13c" marker and explain-back
  questions;
- pins the agent sha (`CURRENT_AGENT_SHA`) in the same commit;
- runs `make test`, `make lint`, `check_s0_stable.py` and the S1 frozen hashes.

**S0-linked** changes with L1 / L2 (no LLM). Its committed pilot records are not rewritten; a
new hybrid-on S0-linked run goes to new files as a diagnostic. One labelled local qwen dev re-run
at the end, as in S13b; Gemini only by the owner, after a quota plan.

## Change log

- 22 Oct 2026: v0.1. Design only, every Decision PENDING. Offline measurements:
  - F1 (d1) recovers 37 / 55 consistent claims, 0 inconsistent, 0 trace;
  - the F6 gate separates all 11 fixtures without a threshold;
  - L1 / L2 linker cases;
  - L3: 235 / 506 chunk ids move.

  Seed experiment (local Ollama, owner protocol): seed null 4 / 12 prompts vary, seed 42 0 / 12.
- 22 Oct 2026: v1.0. Owner decisions:
  - approved: F1 (d1) + guard; the F6 gate with a re-measure condition; L1 with four negative
    tests; L2; L4 no change; L5 no rule; A1; A2 (a); the Ollama seed 42 for S1 and S4, with the
    Gemini seed implemented but off pending a one-call owner smoke;
  - deferred: L3 (both parts) to after v1.0.
