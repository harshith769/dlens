# S12a session report: agent parity (A1–A5)

**Date:** 20 Oct 2026. **Branch:** `s12-agent-parity` (pushed, not merged). **Design:**
`docs/plans/s12-design.md` v1.0. **Cloud LLM calls:** 0. **Scores:** none computed or reported.

## What changed, and the decisions

| step | commit | what |
|---|---|---|
| 1 | 495a80e | Design v1.0: every owner decision of 20 Oct recorded (A1–A5 for S12a, B1–B8 for S12b). ADR 0026 Accepted, spec §0 row 33. ADRs 0025/0027/0028 stay Proposed |
| A1 | 863fac4 | `ANSWER_SYSTEM` = S1's frozen text with one named substitution (`"the c_ ids"` → `"the e_/s_ ids"`, S4's wording at 5996c09); sha256 `4bb98f41…` → `1bbca639…`. `DRAFT_SCHEMA` byte-equal to `S1_DRAFT_SCHEMA` (moved here from A2, owner-approved). Parity test with a named `ALLOWED_DIFFERENCES` list (substitutions; S4-only appended lines, empty). Clarification rule: the model's candidates are ignored when code decided (ambiguity policy, or any code link to a column) or an id is not an exact graph column |
| A2 | 8d67464 | `attach` copies `reach_verdict` (source `llm`); R9 option (b) adds the field check; salvage after an R9 failure sets the fact's verdict with source `code`. Import-boundary test: `src/dlens/agent` imports nothing from `eval/` or `dlens.gold_spec` and names no `eval/` path (path-boundary regex). Demo presets stamped with their recorder's prompt sha (see Presets) |
| A3 | a3315a2 | `search_docs` cites through `chunk_citation` (side record and hit). All 506 fixture chunks equal S1's ledger citation; chunk-id list sha256 unchanged. The `dlens search` CLI prints the index range (`cli.py`), so its output does **not** change; only the tool payload does |
| A4 | f8c8b80 | `eval/systems/s4.py` + `make eval-s4`; `RunRecord.question_id` and record-level `cache`; M15 manifest with prompt / schema / tool-spec hashes, one agent-code sha256, tool settings, hybrid flag + index key, cache dir and counts. Join stays exact text (metrics.py unchanged). `dev_report.py` / `eval-smoke` deprecated until the v0.3 tag |
| A5 | 268a42f | `impact_downstream` direct + indirect, payload shape B; `trace_upstream` honours `include_indirect` (default direct). Indirect edges citable (`key`, `indirect: true`), cited by from column or guarded clause key. R3 by kind (shared fixture with M7), R8c direct-only bridges, `r_` fact decides over direct + indirect and states the direct reading. Traversal allowlist: A5-CHAIN, A5-CHUNK-META, A5-IMPACT-DIRECT-LABEL; A5-R9-DIRECT-READING documented in the test docstring |
| 3 | d6d8e61 | Explain-back questions for the new behaviour (agent, validator, retrieval, tools, graph, indirect-edges, eval-dev, deploy) |
| fix | 54519db | Owner decisions at the step-4 STOP: the collapsed over-cap line reads "+K more columns in M models (<kind>)" (tested on a synthetic 150-model payload); the synthetic_shop tool test checks every indirect record against the **gold spec's** 621 indirect edges, not the engine's |
| test | 81e08bf | `scripts/check_s0_stable.py`: S0 stability, equal except one named field |
| A6 | 60fdd13 | Regenerate budget fix (owner decision before merge; s12-design v1.1 A6): two-stage bound, answer budget `cap − REGENERATE_RESERVE` (278), skip-and-salvage fallback. See "Fixed in S12a" |

Offline facts measured on the way (no LLM):
- On the real corpus graph all 621 indirect edges cite at `line` (598 by the from column, 23 by
  the guarded clause key), and metrics M7 accepts all 621.
- Every dev impact payload fits the 1,500-token cap uncut (1,114–1,462). Only
  `stg_products.product_id` (175 columns, in no dev question) is cut; its lines collapse.
- `make test` runs `integration`-marked tests in `lint-test` on 3.12 and 3.13 (B8).

## Tests

| where | result |
|---|---|
| local `make test` (agent + ui + retrieval extras installed) | 1,422 passed, 19 skipped |
| CI lint-test (3.12): `make test` | 1,380 passed, 39 skipped |
| CI lint-test (3.12): core install, no extras | 797 passed, 8 skipped, 71 deselected |
| CI lint-test (3.13): `make test` | 1,380 passed, 39 skipped |
| CI lint-test (3.13): core install, no extras | 797 passed, 8 skipped, 71 deselected |
| CI retrieval | 84 passed, 1 skipped |
| CI core-artifacts (macOS / Windows) | 56 passed / 56 passed |
| CI demo-install | success (boot + preset click) |

CI run 39483251022 (head 60fdd13, after A6): all six jobs green. (Before A6, run 39478005749 on
81e08bf: all green, 1,374 passed in lint-test.) New tests needing an extra use
`pytest.importorskip`: `test_s4.py` (httpx, lint-test), the A3 parity test (bm25s + httpx,
retrieval job).

## Checks before the smoke

- `git diff main -- eval/systems/s1.py eval/questions eval/metrics.py`: **empty**.
- **S1 hashes:** `s1.frozen_hashes() == FROZEN` (system `fb820558…`, schema `60364350…`,
  citation_rule `159a0020…`, all eight equal).
- **Paths / usernames:** the branch diff against main (lock files excluded), added lines grepped
  for Linux home, macOS user and Windows user path prefixes: no hits. (The pattern is not quoted
  here: `tests/unit/test_no_absolute_paths.py` would flag it.) Bare username in added lines outside the repo URL and the Streamlit URL: no hits.
- **Agent modules importing `dlens.gold_spec`:** none.
- **S0 stability** (owner decision: equal except `timings.total_ms`):
  `scripts/check_s0_stable.py` re-runs S0 into a temp dir and compares with the committed
  `eval/runs/s0/` records, excluding exactly `EXCLUDED = ("timings", "total_ms")` (wall-clock
  latency). Result: s0-gold 84 records, 0 differ outside it (17 differ in it); s0-linked 84
  records, 0 differ outside it (41 differ in it). Committed S0 files untouched.

## A2 raw-view verification (verify only, no change)

After an R9 regenerate, `record.draft` still holds the **first** (pre-validation) draft:
`loop.py` sets it once in the answer phase (after at most one JSON repair, which is not
validator-triggered), and `_regenerate` writes only `regenerate_draft_raw`. Metrics' raw view
(`from_record`, `reach_verdict`) reads `record["draft"]`, matching metrics-design v1.1 M3 rule 5.
Raw never includes a validator-triggered regenerate. Pinned by
`test_flow.py::test_raw_view_reads_the_first_draft_never_the_regenerate`. `eval/metrics.py`
was not edited.

## Presets

The 10 committed presets were stamped with `answer_system_sha256 = 4bb98f41…` **after the fact,
from git history**: `ANSWER_SYSTEM` was unchanged from aeb51ab (3 Oct) to 863fac4 (20 Oct), and
the presets were recorded on 4 and 17 Oct. The recorder did not write these stamps. From now on
it does: `scripts/record_presets.py` writes through `demo.preset_json`, which stamps the current
sha (checked by `test_preset_file_round_trips_and_revalidates`), so S15's re-records are stamped
automatically. For the 10 v0.2 presets the byte-equal replay and revalidation are skipped
("recorded with the v0.2 system; re-record in S15"); they must still load with the current schema
and every cited id must resolve. The live demo shows recorded answers and is unaffected.

## Crash smoke (local qwen3:4b, 10 dev questions)

`DLENS_PROVIDER=ollama DLENS_CACHE_DIR=eval/cache/s12a-smoke`, new empty cache dir, hybrid on
(index reused), output in `eval/cache/s12a-smoke-out/` (gitignored). 36 local LLM calls,
2 min 18 s. `git status` clean afterwards.

- **Crashes:** no Python exception; 10 of 10 records written. One run ended in a caught
  `InputTooLarge` (dev-67, below).
- **Schema:** all 10 records load as `RunRecord`, all 10 final answers as `Answer`.
- **`reach_verdict`:** the key is present on all 10 final answers. dev-10: `no` (source `llm`);
  dev-74: `yes` (source `llm`). Drafts carry the key on the 8 runs that reached the answer phase
  (dev-46 and dev-93 ended before it).
- **Records:** `project` relative (`corpora/synthetic_shop`) and `question_id` set on all 10;
  the id↔text check passed.
- **Cache fields:** record `cache` = `miss` on all 10; `tokens.cached_calls` 0.
- **Manifest:** all expected fields present; `view` `raw|validated|augmented`, `hybrid` true with
  the index key, `required` = the 10 ids, `cache` `{dir: eval/cache/s12a-smoke, hits: 0,
  misses: 36, records: {hit 0, miss 10, partial 0}}`.

Observations (no code changed for 2–4):
1. **dev-67, budget bug (crash class): fixed in S12a (A6), see below.** The answer prompt was
   trimmed to fit (3,827 → 2,958 est. tokens, 25 edges dropped). The validator's regenerate then
   added its failure list and came to 3,107 > 3,000, so the client raised `InputTooLarge` and the
   run was refused.
2. **dev-46:** still refused "no lineage evidence" (B7's case, as recorded).
3. **dev-93:** refused on the unknown model with the tool error (expected for its type).
4. **dev-07:** the first draft set `reach_verdict: "yes"` on an impact question with no `r_`
   fact (no R9 field check without a fact, by design). The regenerated draft said `no`. Metrics
   reads the field only on yes/no questions.

## Fixed in S12a: the regenerate budget (A6, owner decision before merge)

- **Cause:** the answer phase trimmed to the full cap, and the regenerate turn had no reserved room
  and could not shrink its list below one line (the fact line was unclipped). A1 + A5 made it
  reachable.
- **Fix (s12-design v1.1 A6):** the answer prompt is trimmed to `cap − REGENERATE_RESERVE`. The
  regenerate is built on the original answer prompt, never on the JSON-repair exchange, so the
  reserve is `max(repair turn 170, minimal regenerate 278) = 278 est.`, computed from the
  constants. The failure list then fills the room left: fact first, rule order R1–R9, at most 9,
  "+K more failures". If not even the minimal list fits, the regenerate is skipped and the answer
  salvaged (`+regenerate_skipped_budget`). No call is sent over the cap.
- **Rejected:** a worst-case reserve (~803 est.), −33% evidence budget on every question.
- **Offline replay** (`scripts/replay_answer_budget.py`; offline approximation: 18 Oct tool calls,
  today's tools, hybrid off; 67 answer-phase records):

  | threshold | trimmed |
  |---|---|
  | cap, before A6 | 2 / 67 (dev-67, dev-69) |
  | cap − 278, A6 | 2 / 67 (dev-67, dev-69) |
  | cap − 803, rejected | 5 / 67 (+ dev-08, dev-09, dev-72) |

- **dev-67 local re-run** (qwen, new empty cache `eval/cache/s12a-dev67`, output gitignored): no
  `InputTooLarge`; the record loads; 3 LLM calls (tool, tool, answer); the answer prompt was
  trimmed (31 ids dropped) to 2,715 est., under 3,000 − 278 = 2,722. `stop_reason`
  `model_done`; the first draft passed validation, so no regenerate was needed and the regenerate
  path was not exercised live (the unit tests cover it: trimmed evidence + forced regenerate,
  repair + regenerate, and the skip-and-salvage case). Not refused; `reach_verdict` present. No
  scores.

## Open items for S12b

- dev-67's tool payload is 1,462 of 1,500 tokens (closest to the cap of any dev impact
  question).
- B1–B8 as decided in s12-design v1.0. B6: re-count the expected R9 regenerates (new `r_`
  facts) for the S13 quota line. B4: the A1 claims phrase becomes `"the e_/s_/c_ ids"` (one
  `ALLOWED_DIFFERENCES` entry); S0-linked hybrid-off kept and labelled, hybrid-on added.
- Reuse `scripts/check_s0_stable.py` after S12b's changes.
- S15: re-record all 10 presets and empty `SKIP_REPLAY`; the v0.3.0 tag is blocked while it is
  non-empty (v0.3-plan "done when" 8).
- Explain gate: the S12a explain-back questions in agent, validator, retrieval, tools, graph,
  indirect-edges, eval-dev and deploy.
