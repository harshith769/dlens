# Explain: agent loop (`src/dlens/agent/{loop,context,evidence,answer,prompts,runlog}.py`)

## What it does
`ask(question, client, toolbox, logger)` (CLI: `dlens ask "…" -p PROJECT [--json]`) turns a
question into an `Answer`: a short text plus claims, each citing edge ids (`e_…`) and excerpt ids
(`s_…`), with file and line citations attached by code. It runs in two phases, then a validator
hook, and writes one JSONL record per run.

```
question ─► TOOL PHASE  (≤5 LLM calls, tools on, history compacted to fit)
              │  Toolbox ledger: every id the tools emitted + full records
              ▼
            ambiguity policy (code): chain / per-candidate / clarification
              ▼
            ANSWER PHASE (1 call + ≤1 repair, no tools, JSON schema)
              prompt = question + evidence rebuilt from the ledger
              ▼
            attach citations (code) ─► validate R1–R7 ─► regenerate once ─► salvage / refuse
```

## Budgets
- **Calls.** At most 8 LLM calls per question, counting every call: ≤5 in the tool phase
  (repairs and retries included), then the answer call, one answer repair and the validator's
  "regenerate once" (see validator.md). Tool calls that code makes itself (chain mode) are not LLM calls.
- **Tokens.** Every call is measured with `estimate_tokens` (the same function `LLMClient` uses
  for the 3,000 cap) before it is sent. The fixed costs are small on purpose:

  | Part | Est. tokens |
  |---|---|
  | Tool-phase system prompt | 294 |
  | Four tool specs (trimmed, see tools.md) | 437 |
  | Answer-phase system prompt | 201 |
  | Answer JSON schema (counted as input) | 184 |

  A `trace_upstream` payload can reach ~900–1,500 tokens, so two big results fit in the tool
  phase before compaction starts. On the synthetic_shop smoke questions the largest call was ~1,714.

## Tool phase and the budget manager (`context.py`)
Messages are `[system, user(question)]` plus assistant tool calls and tool results. Before each
call `fit()` checks the estimate. If it is over the cap, the oldest tool message is replaced by
a **digest**, then the next oldest, newest last:
- level 1: trace edge lines deduplicated across paths; impact `column via e_id`; SQL
  `excerpt_id + file + range` (text dropped); resolve candidate ids;
- level 2: also drops edge expressions and impact models and exposures.

Every id the original payload showed is still in the digest (tested at both levels). Each
compaction is logged. If even full compaction does not fit, the tool phase stops (`budget`). The
phase also stops when the model replies without a tool call (`model_done`), at 5 calls
(`step_cap`), or after two turns that only repeat earlier calls (`repeating`).

**Dedupe.** Calls are keyed by tool name and canonical arguments: defaults filled in, strings
lower-cased, numeric strings coerced, column ids resolved through the graph. A repeated call is not
re-run. The earlier result's current content is returned and the step is marked `deduped`.

## Why the answer prompt is rebuilt from the ledger
The answer prompt is not the chat history. It is the question plus an evidence list built from
`toolbox.log`, keeping only ids in `toolbox.emitted_ids`:
- edges as compact strings (`e_…: a -> b [KIND: expr]`);
- excerpts as `s_…: file:a-b "<snippet>"`;
- context lines with no id (impact models and exposures, ambiguous resolve candidates).

Reasons:
1. **Size is bounded by evidence, not by conversation length.** Assistant chatter, repeated
   calls and error retries cost nothing here.
2. **Only real ids can appear.** An id the model typed in its own text (it may be wrong) never
   reaches the answer prompt, so the answer phase cannot "learn" a fake id from the history.
3. **Compaction never costs evidence.** The tool phase may have digested a payload to save room.
   The answer phase still gets the full edge strings and SQL snippets from the ledger.

If the answer prompt is still over the cap, `trim()` drops the most distant evidence first (by hop
distance from the queried column), so every path keeps a contiguous run from the column outward.
It then sets `partial_evidence` and tells the model to say the answer may be incomplete.

## Ambiguity policy (code, not the LLM)
For an `ambiguous: true` resolve_entity result, the tie set is the candidates within 0.05 of the
top score. If the question names exactly one of them (full `model.column`, or a model name only
one of them has), nothing happens. Otherwise:
- **chain mode**: all tied candidates are columns on one lineage chain, whatever the count.
  Code traces the most downstream one if the model did not, and the prompt says "these names are
  the same column at different layers". This covers synthetic_shop's `refund_amt` /
  `refund_amount` near-duplicates.
- **per-candidate**: not one chain and ≤3 candidates. The model answers for each.
- **clarification**: not one chain and >3 candidates. Code returns `clarification {question,
  candidates}` with no answer call, so the LLM cannot invent a candidate.

## Answers and citations (`answer.py`)
The LLM writes `AnswerDraft {answer_text, claims[{text, ids}], confidence, refused,
refusal_reason}` under a flat JSON schema (Ollama `format`, Gemini `response_json_schema`). Code
does the rest:
- it splits `ids` into `edge_ids` (`e_`) and `chunk_ids` (`s_` and anything else);
- it computes `subgraph`;
- it looks up each id's citation in the ledger.

The model never types a file or a line. `render()` prints `[file:line]` markers (`[file]` for
model-level citations, `[?id]` for an id the ledger does not know).

**`confidence` is the model's self-report.** It is shown and logged, but the validator and the
benchmark scoring never use it.

## Failure handling
- **Malformed tool call** (a call written as text, or an Ollama tool-parse error): one repair
  turn with the error, then a refused answer.
- **Invalid answer JSON**: one repair with the error, then a refused answer.
- **Tool error payloads** go back to the model as normal tool results.
- **Provider errors**: a non-retryable `ProviderError`, `QuotaExceeded` or `InputTooLarge`
  becomes a refused answer with the reason. A retryable provider error gets one retry.
- **No tool call at all** (seen live on a false-premise question, where the 4B model asked for a
  column id the question already contained): if the question names an exact, existing
  `model.column`, code traces the first one. That is a `code` step, not an LLM call, like chain
  mode, and the answer phase runs normally. The system prompt also says "Questions may contain
  false assumptions; check them with the tools before answering" (tool phase now 721 estimated
  tokens with specs, cap 900).
- **No citable evidence** (unknown column): refused by code with the tool errors as the reason,
  with no answer call.

## Draft logging (`runlog.py`)
One JSONL line per run in `$DLENS_RUN_DIR` (or `$XDG_STATE_HOME/dlens/runs`), one file per day. A
record holds:
- question, provider, model and params;
- every step (phase, estimated and real tokens, cached, latency, text, tool calls, and each
  result's `llm_payload` and `side_records`);
- compactions, ambiguity decision and evidence ids;
- the raw pre-validation draft (`draft_raw`) and the parsed draft;
- validation result, final answer, timings and token totals.

That is enough to replay the no-validator ablation offline.

## Alternatives rejected
- **Single-phase ReAct with full history.** Simple, but a 3K cap overflows after 2–3 traces,
  and the final answer is then written from a truncated or compacted history. The answer would
  depend on what happened to fit, not on the evidence.
- **LangChain / LangGraph.** A large dependency that hides the exact messages, token counts and
  cache keys this project must control and log. Spec §5 says no agent framework. Our loop is a
  few hundred lines and fully tested with a scripted provider.
- **Raising the cap.** ADR 0007 fixes ~3K input tokens per call to keep the free-tier quota plan
  and the 4B local model (8K context, 6 GB GPU) workable. Raising it would also make the
  benchmark cost depend on conversation length.
- **Letting the LLM decide ambiguity.** A 4B model picks one candidate silently. Code can check
  the lineage chain exactly.

## Explain-back questions
1. The tool phase compacted a `get_model_sql` result down to its `excerpt_id` and range. Why can
   the answer phase still quote the SQL, and why would that be impossible in a single-phase loop
   that answers from its own history?
2. "Where does refund amt come from?" ties four candidates on synthetic_shop and gets no
   clarification. Walk through the policy: which candidate is answered for, who made the extra
   tool call, and why it does not count toward the 8-call cap.
3. In the live smoke, question b cited `e_4b2_403a`, an id no tool emitted. Which part of this
   design guarantees the id gets no citation, and which part (not yet written) must remove the
   claim? What would `draft_raw` in the run record let you measure later?
