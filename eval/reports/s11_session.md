# S11 session report: S1 vector-RAG baseline + OpenAI-compatible adapter (20 Oct 2026)

Branch `s11-s1-baseline`. No cloud LLM call was made. Local Ollama calls: one smoke on its
OpenAI-compatible `/v1` endpoint, and the S1 dev run (96 calls + 1 trial, all cached in
`eval/cache`). No frozen file was touched (test.jsonl, external.jsonl, `.sha256`), and neither
were `src/dlens/lineage/`, the validator, the linker scorer, or S4's prompts/loop/`DRAFT_SCHEMA`.

## What was built

| step | commit | what |
|---|---|---|
| 1 | `docs:` ×2 | `docs/plans/s1-design.md` (B1–B9; owner decisions: B2 skip-and-pack without a k ceiling, B5 interpretation deferred, the rest as recommended) and ADR 0024 (accepted) |
| — | `feat(retrieval):` | seed-card citation helper `dlens.retrieval.citation` (owner decision, before any S1 run; see below) |
| 2 | `feat(llm):` | OpenAI-compatible adapter (`httpx`), Groq as a preset, key-safety sentinel test, cloud guard (non-local needs a key and a daily budget). `groq` left the `agent` extra |
| 3 | `feat(agent):` | `Answer.reach_verdict` / `reach_verdict_source` (ADR 0024, additive). S4 answer phase pinned by sha256 |
| 4 | `feat(eval):` | `eval/systems/s1.py`, `make eval-s1`, shared manifest writer `eval/systems/manifest.py`, metrics.py 1.2.0 (`from_s1_record`, ADR 0024 verdict accessor; no definition change) |
| 5 | `feat(eval):` | S1 smoke run on the 96 dev questions (local qwen3:4b) + `scripts/s1_diagnostics.py` |
| 6 | `docs:` | this report, CHANGELOG, carry-forwards |

**Seed-card citation (owner decision).** The first attempt put the header-line rule into the
chunker. Chunk ids hash the line range, so the 73 seed-card ids changed, rows re-sorted, and
rank ties broke differently. Text, meta and vectors were byte-identical, yet one linker-test
top-1 moved (95 → 94 of 109) and dev-10's sanity rank went 1 → 2. Per the owner's rule, I
stopped. The chunker change was reverted (linker and sanity reports confirmed identical to main,
build times aside), and the rule now lives in one helper that ledgers use.

**Checks that nothing else moved.** The committed S0 records re-score to the committed S0 reports
byte for byte, version stamps aside (now a CI test). The local 18 Oct S4 smoke records re-score
identically in all three views. S0's records and manifests are unchanged after the
manifest-writer refactor (timings and commit hash aside). The `uv.lock` diff only removes
groq 1.7.0 and lists `httpx` under the `agent` extra. `demo/requirements.txt` is unchanged.

## S1 smoke beside S0 (96 dev questions)

Report only, not the pilot table. S1 = local qwen3:4b-instruct-2507-q4_K_M via Ollama, hybrid
retrieval (index reused), metrics.py 1.2.0 / metrics-design 1.1. The S0 rows are the committed S10
reports (metrics.py 1.1.0). The S0 regression test shows 1.2.0 gives the same numbers. S0-linked
is the linker with the hybrid stage off. Per the brief, S1 is not placed beside the S4 smoke run.
95% bootstrap CIs; n shown.

| metric | S0-gold | S0-linked (hybrid off) | S1 (qwen3:4b) |
|---|---|---|---|
| node-set F1, pooled | 1.000 (n=68) | 0.868 [0.78, 0.94] (n=68) | 0.248 [0.17, 0.33] (n=68) |
| trace F1 | 1.000 (n=44) | 0.909 [0.82, 0.98] (n=44) | 0.303 [0.19, 0.41] (n=44) |
| impact F1 | 1.000 (n=24) | 0.792 [0.62, 0.92] (n=24) | 0.148 [0.07, 0.24] (n=24) |
| yes/no verdict accuracy | 1.000 (n=6) | 1.000 (n=6) | 0.500 (n=6) |
| refusal accuracy | 1.000 (n=9) | 1.000 (n=9) | 0.556 (n=9) |
| false-refusal rate | 0.000 (n=75) | 0.107 [0.04, 0.17] (n=75) | 0.011 [0.00, 0.05] (n=87, incl. Ask) |
| chain / clarify correct | 1.000 (n=2) / 1.000 (n=1) | 1.000 / 1.000 | 0.000 (n=2) / 0.000 (n=1) |
| false-premise explicit rejection | 1.000 (n=4) | 1.000 (n=4) | 0.250 (n=4) |
| path node coverage | 1.000 (n=29) | 0.897 [0.76, 1.00] (n=29) | 0.207 [0.07, 0.34] (n=29) |
| fully correct | 1.000 (n=84) | 0.893 [0.82, 0.95] (n=84) | 0.179 [0.11, 0.26] (n=84) |
| hallucinated-node rate | 0.000 | 0.000 | 0.000 (n=76) |
| citation validity, per answer | 1.000 (n=71) | 1.000 (n=63) | 0.322 [0.22, 0.42] (n=90) |
| citation validity, per citation | – | – | 132 / 282 |
| citation coverage | 1.000 | 1.000 | 1.000 (n=90) |
| latency p50 / p95, uncached | – (no LLM) | – (no LLM) | 7.7 s / 14.7 s (95 uncached) |
| tokens per question, mean / p95 | 0 | 0 | 2,329 / 2,547 (1.0 LLM call) |

S0 skips the 12 Ask questions (no LLM), so its false-refusal n is 75. S1 answers them (for the
owner's blind hand scoring, M11), so its n is 87. Full S1 report: `s1_smoke_dev.md`.

## Pipeline health (`s1_smoke_dev_health.md`)

- 96/96 records, run complete. Answered 90, refused 6, clarification 0.
- JSON: 0 parse failures, 0 repairs, 0 provider retries. Exactly 1 LLM call per question
  (96 total).
- k used: min 21, p50 28, p95 39, max 45. Every prompt stopped `budget_full`, with 0–38 est.
  tokens unused (mean 13). Est. input 2,762–2,800 of the 3,000 cap (2,800 = cap − reserve).
- Cache: a full re-run made 0 uncached calls and produced identical answers and evidence.
- Ids: 293 cited, 1 not among the shown chunks (kept, uncited). 14 citations of seed cards (header
  line).

**Retrieval diagnostic** (report only, outside metrics.py). The gold target's own column card was
shown for 86 of the 87 questions that have a card (the 9 unanswerable have none). One paraphrase
question had it retrieved but not shown. By this measure, 64 of 65 losses are "LLM misses". This
is a lower bound on retrieval's share: a trace or impact answer needs every hop's evidence, not
only the target's card.

**Where S1's invalid citations come from** (structural facts, read after the run; no S1 setting
changed, B8):
- 97 of 150 invalid citations are on claims that name no `model.column` id. M7's excerpt rule
  needs a column the claim names, and the model wrote bare names despite the prompt line.
- 43 citations point at column cards with a YAML description, and 42 of them are invalid. The
  card's citation is its `description:` line, and the column's name is on the `- name:` line
  above it. This is a chunk-citation fact of the same class as the seed cards. It affects S4
  equally once `search_docs` is wired in (S12). **Owner note below.**

## Carry-forwards

**S12 (agent upgrades):**
- Adopt S1's shared answer-prompt lines **and** its three new lines (`model.column`,
  `reach_verdict`, `clarification_candidates`) verbatim for S4. Then switch the parity test in
  `tests/unit/eval/test_s1.py` from "S1 vs the S4 snapshot at 776724f" to "S1 frozen vs S4 live".
- S4's draft schema gets `reach_verdict`. R9 salvage sets `reach_verdict_source = "code"`, and the
  S4-raw view counts only `llm`. The metrics accessor already reads that shape.
- When `search_docs` is wired in (G4), S4's ledger cites chunks through
  `dlens.retrieval.citation.chunk_citation`, so seed citations follow one rule for S1 and S4.
- Structured interpretation `{from, to}` becomes the M9 rule for every system (B5 deferred it
  here). Before D5b questions with `gold.interpretation` are scored, decide whether S1 is re-run
  with that field (a recorded B8 change).
- `question_id` in `RunRecord` (M12 join); the shared manifest writer is ready for S4.
- **Owner decision needed (raised here, not acted on):** YAML-description column cards cite only
  their `description:` line, which doesn't contain the column name, so M7 marks those citations
  invalid. Options: extend the shared citation helper to cite the `- name:` line through the
  description (as was done for seed cards, without touching chunk ids), or leave it and report
  it. Either way it applies to S1 and S4 alike, and it needs deciding before the S13 pilot. Any
  change is a recorded B8 change and re-runs S1. S1's evidence header shows each chunk's
  citation, so the prompts change too: new LLM calls, free on local qwen.

**After the pilot (linker unfrozen):** move the seed-header rule (and any description-line rule)
into the chunker's metadata, and make rank tie-breaking independent of chunk ids, which hash
citation metadata.

**S13 quota estimate (Gemini pilot):** S1 96 calls expected, 192 worst (one JSON repair each).
S4 ~480 expected, 768 worst. Pilot total **≈ 576 expected, ≈ 960 worst** (was 864), 2–3 quota days
at 380 usable/day. On local qwen, S1 needed 0 repairs on dev. S1 on Gemini must be launched by
the owner with `--allow-cloud` after confirming the quota plan.
