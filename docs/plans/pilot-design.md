# Pilot design (S13, v0.3 done-when 5, D4)

**Version:** 0.1 (21 Oct 2026). **Status:** records and sampling decided by the owner before any
pilot run. The cloud plan (§3) is filled in at STOP B (v0.2).
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
  1.0 carries more run-to-run noise than the qwen run-to-run difference seen in S12b (±0.04).
- **S1 vs S4 is compared within each panel only.** The panels differ in model and temperature, so
  no cross-panel difference is reported as a system effect. The pilot table states the
  temperature difference.

## 3. Cloud plan

To be filled in at STOP B (v0.2): model id, expected and worst-case calls, the daily budget and
its stop rule, the day order, exact commands, and the quota reset time in IST.

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

## Change log

- 21 Oct 2026: v0.1. Pilot records and sampling fixed by the owner before any pilot run (§1, §2).
  qwen S4 reuse check passed (equal agent-code sha).
- 21 Oct 2026: §4 post-pilot fix candidates F1–F4 (owner, after STOP A). No code change.
