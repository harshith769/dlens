# Spec delta: v1.5 → v1.6

**For Claude Code.** Apply these changes to `docs/DLENS_SPEC.md`. The current file is the base: read it first, keep everything not mentioned here, and match its existing style (plain English, tables, short sentences). Where an item below is already true in v1.5, skip it and say so in the report. Show the full diff before committing.

Source of each change: `docs/plans/v0.3-plan.md` Section 1 (rows 1–16).

---

## Title and version line
- Version → **1.6**, dated 4 Oct 2026: "v1.5 plus the v0.3 plan, ownership model v2, and the product track."

## Section 0: change log
Append rows, numbered from the next free row (v1.5 ends at row 20):

| Change | Reason |
|---|---|
| Ownership model v2: Claude Code writes all code; the owner owns design, gold data, acceptance and an explain gate before each tag (replaces "hand-written" zones) | Decided 3 Oct 2026; matches how v0.1–v0.2 were actually built |
| Local benchmark model is `qwen3:4b-instruct-2507-q4_K_M` (skip if already recorded) | The thinking build leaked reasoning; 4B instruct fits the GPU fully |
| OpenAI-compatible adapter replaces the Groq-specific SDK; Groq is one configuration | One adapter covers Groq, OpenRouter, LM Studio, vLLM, OpenAI and real users' own keys |
| Artifact-only ingest for any sqlglot dialect, plus a catalog-less fallback | Real users are on Snowflake/BigQuery/Postgres/Databricks and already have artifacts; also needed for set E |
| Dense retrieval uses numpy exact search, not LanceDB; embeddings on CPU | ≤ 20k chunks is milliseconds in numpy; Ollama holds the GPU; fewer deps |
| Answer schema: additive `premise_corrected` and per-claim `origin` (model, repaired, completed, augmented) | Needed for honest three-way S4 reporting and the UI badge |
| S4 reported three ways: raw, validated, augmented (coverage completion) | Separates what the LLM did from what code added |
| Yes/no questions scored on verdict accuracy | A correct "No" has nothing to cite |
| Perturbation oracle added as a third, dynamic source of truth on the synthetic corpus | Spec and parser are both AI-written; independence must be shown |
| System freeze together with the test freeze (prompts, validator version, model IDs, tool code hashed) | Rules changed often in dev; test numbers must come from a fixed system |
| Two-track roadmap: research (to v1.0) + product (v1.1 MCP server, v1.2 PR impact bot) | Build velocity is higher than planned; product work uses the surplus without blocking research gates |

## Section 2: locked decisions (edit rows)
- **Scope:** add "Ingest also works from existing dbt artifacts for any sqlglot-supported dialect; dbt-duckdb remains the build runtime for our own corpora."
- **Retrieval:** "BM25 (`bm25s`) + dense (`bge-small-en-v1.5` on CPU, numpy exact search), fused with RRF; no reranker in v1."
- **LLM: local:** `qwen3:4b-instruct-2507-q4_K_M` via Ollama, `num_ctx` 8192 (if not already).
- **LLM: cross-check and judge:** "OpenAI-compatible adapter; Groq `openai/gpt-oss-120b` if its free tier still allows, else another free OpenAI-compatible endpoint; decided before v1.0 judge calibration."
- **UI and hosting:** add "plus a local UI on any ingested project (`dlens ui --project`)."

## Section 5: build vs avoid
- Build list: add "Artifact-only, multi-dialect ingest with catalog-less fallback", "Perturbation oracle (synthetic corpus only)", "Local UI on any project".
- Build list: change "Three LLM adapters (Gemini, Ollama, Groq)" → "LLM adapters: Gemini, Ollama, OpenAI-compatible".
- Add a short "Product track (after v1.0, never blocks research gates)" list: MCP server with `verify_answer` (v1.1); PR impact bot (v1.2); scale + Diff (v1.3+).
- Avoid list: keep everything; add "Hosted service that receives user code; telemetry".

## Section 7: lineage engine
- Replace "This module is hand-written by you (Section 17)" with "Owner-gated module: changes only when an approved plan names it, with an explain doc (Section 17)."

## Section 8: retrieval, linking, agent, validator
- Validator: make sure R1–R9, R2r, R8c, regenerate-once and salvage are documented (they should be, from v1.5).
- Add **coverage completion** (code appends missing direct inputs as `origin: augmented` claims; reported separately).
- Add **multi-part / out-of-scope handling** (answer the covered part; name the uncovered part and the question to ask).
- Answer schema: add `premise_corrected: bool` and claim `origin`; note `confidence` is unused and kept only for compatibility.

## Section 9: models
- Local agent row: `qwen3:4b-instruct-2507-q4_K_M` (replaces `qwen3:8b` / fallback wording).
- Cross-check + judge row: via the OpenAI-compatible adapter (Groq or another free endpoint).
- "Hand-coded ML" line: keep the content, drop "hand-coded by you" wording if present.

## Section 10: corpora
- `synthetic_shop` v2: 40–60 models; **every v1 model and column name is kept**; design doc `corpora/synthetic_shop/DESIGN_v2.md`.
- Add the perturbation oracle paragraph (what it checks, what disagreements mean, where the report lives).

## Section 11: evaluation
- 11.2: the existing 20 dev questions are part of the 96 dev questions.
- 11.3: S4 reported as S4-raw / S4-validated / S4-augmented.
- 11.4: judge = a model behind the OpenAI-compatible adapter (Groq if still free); add verdict accuracy for yes/no; add "metrics are defined in `docs/plans/metrics-design.md` (owner-approved) before `eval/metrics.py` is written."
- Add 11.7 **System freeze** (what is hashed, when, and that any change after 7 Dec means re-running every system).

## Section 12: tech stack and repository
- Vectors row: numpy exact search (`.npy`) instead of LanceDB; embeddings on CPU.
- LLM SDKs row: `google-genai`, `ollama`, OpenAI-compatible client (replaces `groq`).
- UI row: Streamlit (pinned 1.65.x); drop `streamlit-agraph` if unused (Graphviz is used).
- Repo tree: replace `[HAND-WRITTEN]` markers with `[OWNER-GATED]`; add `demo/`, `docs/plans/`, `docs/explain/`, `eval/oracle/`.

## Section 14: releases and checklists
- Replace the v0.3 checklist with the M/S items from `v0.3-plan.md` Section 3, grouped by track, each marked with its owner gate.
- v0.3 "Done when": copy the 8 conditions from `v0.3-plan.md` Section 2.
- v1.0 checklist: add "Freeze the S4 system with the test set (11.7)" as the first item next to the question freeze.
- Replace the v1.x line with: v1.1 MCP server + `verify_answer` (target 7 Feb 2027, only if v1.0 runs are done); v1.2 PR impact bot; v1.3+ scale and Diff.
- Keep all dates: v0.3 29 Nov, freeze 7 Dec, v1.0 3 Jan 2027, hard stop 7 Feb 2027.

## Section 17: who does what
Replace the "hand-written" rule and table with **ownership model v2** from `v0.3-plan.md` Section 6 (owner: design, gold data, acceptance, explain gate; Claude Code: all code; Claude app chat: planning, plan review, mentoring). Keep the anti-patterns, rewritten: "accepting code you can't explain after reading its explain doc"; "any AI tool touching frozen files"; "asking Claude Code to build a whole release in one session".

## Section 19: open-source and resume
- v0.2 row: replace the planned line with the shipped one (PyPI `dlens-lineage`, live demo, validator).
- Interview prep: replace "What did you write vs AI?" with the honest phrasing from `v0.3-plan.md` Section 6.

## Section 20: risks
Add the v0.3 risks table rows from `v0.3-plan.md` Section 7 that are not already present.

## Section 21: handoff prompts
Replace Prompt A with a pointer: "Start a new Claude app chat by attaching the latest HANDOFF.md (kept outside the repo, in the handoff bundle), v0.3-plan.md and product-north-star.md, and paste the starter message from HANDOFF.md."
