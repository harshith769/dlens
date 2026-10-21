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
            attach citations (code) ─► validate R1–R9 (+R2r, R8c) ─► regenerate once ─► salvage / refuse
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
- level 1: trace edge lines deduplicated across paths; impact: its grouped `model.column e_id`
  items and "+K more" lines (S12a); SQL
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

**Impact evidence (S12a, A5).** Impact results keep the tool's grouping: a context header per
(depth, kind) group ("impact of X, depth 2 [JOIN]:"), then one line per column. A direct column
keeps today's edge string (with its expression, so "how" is answerable); an indirect one is
`model.column e_…`. When `trim()` cuts columns it writes one "+K more columns in <model> (<kind>)"
line per cut group, counted in the budget, so a cut is never silent.

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

**The model's own clarification (S12a, s12-design A1).** The answer prompt (S1's text, see
below) lets the model list `clarification_candidates`. Code decides first: the list is logged (it
stays in the record's `draft`) and ignored when
1. the ambiguity policy above decided (chain, per-candidate, or code clarification), or
2. code linked the question to a column: an exact `model.column` in the question, or any
   resolve_entity result with candidates, or
3. any candidate is not an exact graph column (an invented id is never shown to the user).

Only when none of these hold does the list become `Answer.clarification` (question text from
`prompts.clarification_question`, no claims, not validated). `stop_reason` ends with
`+llm_clarification` or `+candidates_ignored`. Only the first draft is read: a regenerate cannot
turn an answer into a question.

## The answer prompt: S1's text, one named substitution (S12a, A1)
`prompts.ANSWER_SYSTEM` is S1's frozen answer instructions (`eval/systems/s1.py::S1_SYSTEM`) with
exactly one literal substitution: S1's claims line says "the c_ ids", S4's says "the e_/s_ ids"
(S4's wording since 776724f). So both systems get the same three extra lines: write columns as
`model.column`, set `reach_verdict`, list `clarification_candidates`. `DRAFT_SCHEMA` is
byte-equal to `S1_DRAFT_SCHEMA`.

`tests/unit/eval/test_s1.py::test_s1_frozen_vs_s4_live` holds a named `ALLOWED_DIFFERENCES` list:
(i) literal substitutions (each source phrase must occur exactly once in S1's text) and (ii)
S4-only lines appended before the last line, in a fixed order (empty in S12a; S12b adds the
`uncovered_parts` / `premise_corrected` lines and the `c_` phrase as one-line entries). The test
builds S4's text from S1's frozen text and asserts byte equality, and checks that S1's frozen
hashes did not move. Any other drift on either side fails CI. The copy is literal, not an import:
`src/dlens/agent` never imports from `eval/`. The change moved every S4 answer-phase cache key
once (sha256 `4bb98f41…` → `1bbca639…`).

**S12b B4: the `c_` phrase.** The claims line now says "the e_/s_/c_ ids" (the substitution in
`ALLOWED_DIFFERENCES` changed once: `"the c_ ids"` → `"the e_/s_/c_ ids"`), because with an index
the evidence can hold search_docs chunks. The text is the same with or without an index (one
answer prompt, one cache key per question). sha256 `4d626b76…` → `1a35baaf…`.

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

**Structured yes/no verdict (ADR 0024, S11).** `Answer` has two additive fields:
`reach_verdict` (`yes` | `no` | null) and `reach_verdict_source` (`llm` | `code` | null). A source
without a verdict is rejected. Metrics M5 scores yes/no questions only on this field, never on
prose. S1 sets it from its draft (source `llm`). From S12a S4's `AnswerDraft` has the field too
(A1 schema); `attach` copies it with source `llm`, R9 holds it to the `r_` fact, and salvage after
an R9 failure sets the fact's verdict with source `code` (validator.md, R9). The S4-raw view reads
the pre-validation `draft`, so it counts only the model's own value. Old records and presets load
unchanged; new dumps carry two extra `null` keys.

**`premise_corrected` and claim `origin` (S12b B3, ADR 0025, amends 0015).**
- *What:* `AnswerDraft` and `Answer` gain `premise_corrected: bool` (default false); every
  `Claim` gains `origin`: `model` (as drafted), `repaired` (R2r replaced an id), `completed` (R8c
  added an edge; wins over `repaired`), `augmented` (G1 coverage completion, S4-augmented only) or
  `verdict` (salvage's code verdict claim, S4-validated).
- *How:* the prompt gains one S4-only line (`- premise_corrected: true if the question assumes a
  lineage link that the evidence contradicts and your answer says so; otherwise false.`) and the
  draft schema one required boolean, both recorded in the parity test's `ALLOWED_DIFFERENCES`
  (the schema category `s4_schema_properties` is new: A2's byte-equality now holds for S1's
  schema plus exactly the listed properties). `attach` copies the flag and labels every claim
  `model`; the validator relabels only where it already acts.
- *Why LLM-only:* there is no general premise detector to trust, and one built from the 4 dev
  false-premise questions would be tuned on dev. So the field measures the model; S1 and S0,
  which have no field, are scored on the same M10 rule through the negated-mention branch.
- *Rejected:* a code detector with a source field; labelling the salvage claim `augmented` (it
  would take a validator output out of S4-validated).
- The change moved every S4 answer-phase cache key (`ANSWER_SYSTEM` sha256 `1bbca639…` →
  `4d626b76…`) and added 67 est. tokens to each answer call's fixed cost.

**Chunk evidence (S12b, B4).** With an index, the evidence list also holds one line per shown
search_docs hit: `c_… | file:a-b | title "<snippet>"`, the snippet clipped to 400 characters
(double quotes turned into single so the line stays one quoted string), `[star]` / `[model]` when
the citation level is not `line`, and the graph facts the hit carries (`(graph: N direct inputs,
M downstream)`). Chunk lines have priority 0, like excerpts: `trim` drops distant edges first.
The snippet is project text, quoted as data; it may be stale (the SQL wins).

## Uncovered parts and interpretation (S12b B2 + B5, ADRs 0027 / 0028)
- `uncovered_parts: list[str]` is LLM-set: `AnswerDraft` has it (required in the draft schema,
  the `s4_schema_properties` entry) and the prompt one S4-only line with **no example** (`-
  uncovered_parts: list, in a few words each, any part of the question the evidence cannot answer;
  otherwise [].`), so no dev gold word reaches the model (a test checks it). `attach` copies it,
  dropping blank entries; code never adds one.
- `interpretation {from, to}` + `interpretation_source` are code-set in `Agent.ask` from the same
  `entity.dotted_column` reading that writes the lead sentence (which stays): the first reading,
  source `code`. The draft has no such field. It is set on any answer that has the lead, including
  a refusal (metrics M9 only credits answered predictions).
- Both moved the answer-phase cache key once more (the line and the schema property, s12-design
  v1.2: system + schema 591 → 726 est. tokens across B2 + B3 + B4).

## Coverage completion (`augment.py`, S12b B1, spec §8 G1)
- **What:** after validation, code appends what the tools returned and the answer left out, as
  claims with `origin: augmented`. Trace questions (where-from / how-computed wording): each
  direct input of a traced column (a direct edge into it in a `trace_upstream` result) that the
  answer neither names (dotted id in its text or claims) nor cites gets one claim, `"<input> is a
  direct input of <column>."`, citing that edge. Impact questions: every column in
  `impact_downstream`'s `side["full"]` set (which keeps columns the payload cut) not named or
  cited, one claim per (depth, kind) group, `"Also affected at depth N (<kind>): a.x, b.y."`,
  citing the `via` edges.
- **How it stays honest:** it reads `toolbox.log` only, never runs a traversal (a test counts the
  log); nothing is added to a refusal or a clarification; the answer text, the model's claims and
  the subgraph are unchanged. Citations of augmented edges come from the tool's own edge records
  (also for cut impact columns, whose edges were never shown to the model). Augmented claims skip
  the validator and only the S4-augmented view counts them (metrics M3 rule 5; the deprecated
  `dev_report.py` scoring drops them too).
- **Why:** it measures how much of a complete answer the tools had already found, separately from
  what the model wrote (ADR 0016). Impact is included (B1 (b)) so A5's promise, the full set stays
  available to code, holds in the augmented view.
- **Rejected:** trace inputs only (spec text before the note); the full upstream closure on trace
  questions (that would turn G1 into an oracle answer, not a completion).

## Name words and the reachability fact (S12b B6, dev-75)
- **Chain mode:** `_named_candidate` settles a tie when the question names one candidate's
  model, written as-is or with `_` read as a space ("last name in raw customers" →
  `raw_customers.last_name`). All the graph's model names are matched longest first and consume
  their words, so "orders daily" names `orders_daily`, never `orders` too.
- **`r_` fact without exact ids:** with fewer than 2 exact dotted ids, the columns resolve_entity
  linked count too (unambiguous, or a tie the question settles as above), ordered by where each
  query is written in the question; an unsettled tie, a query not found in the question, or a
  third column gives no fact.
- **Relation wording (owner addition):** "upstream of", "downstream of" (spec §7 / §8) and
  "derived from" (the DERIVES edge) now cue the fact; "Y downstream of X" and "Y derived from X"
  ask X → Y, like "depend". Negation in the wording never flips the direction.
- **Why loop.py only:** the linker is frozen until after the pilot; these rules read its output.
- **Known limit:** with hybrid on, the frozen linker ties "customer segment in customer
  leaderboard", so dev-75 still gets no fact (offline replay).

## Per-candidate mode gathers evidence (S12b B7, dev-46)
- **What:** when the ambiguity policy decides `per_candidate` (2–3 tied candidates, not one
  chain), code runs the intent tool on every column candidate (impact wording →
  `impact_downstream`, else `trace_upstream`), rule `candidate_trace`, as "code" steps, skipping
  calls already in the log. If the evidence still has no citable id, code returns the policy's
  clarification (`stop_reason` `+candidate_clarification`) instead of the "no lineage evidence"
  refusal.
- **Why:** the policy decided to answer per candidate but gathered evidence for none when the
  model stopped after resolve_entity (dev-46: refused). Offline replay of dev-46's recorded calls:
  two code traces, 7 citable ids.
- **Unchanged:** more than 3 candidates → clarification with no trace (dev-55 stays a recorded
  policy/gold disagreement); chain mode.

## Failure handling
- **Malformed tool call** (a call written as text, or an Ollama tool-parse error): one repair
  turn with the error, then a refused answer.
- **Invalid answer JSON**: one repair with the error, then a refused answer.
- **Regenerate budget (S12a, s12-design A6).** The answer prompt is trimmed to
  `cap − REGENERATE_RESERVE`. The reserve is the larger of the repair turn (170 est.) and a
  *minimal* regenerate turn (template + fact line + one failure line + "+K more failures", 278
  est.), computed from the constants. It is the larger, not the sum, because the regenerate is
  built on the original answer prompt and never includes the repair exchange. At regenerate time
  the failure list fills the room actually left: the fact first, then lines in rule order R1–R9,
  at most 9, then "+K more failures". If not even the minimal list fits, the regenerate is skipped
  (`+regenerate_skipped_budget`) and the answer is salvaged. No call is sent over the cap. A
  worst-case reserve (~803) was rejected: it would cost every question a third of its evidence
  budget to protect a turn only some take.
- **Tool error payloads** go back to the model as normal tool results.
- **Provider errors**: a non-retryable `ProviderError`, `QuotaExceeded` or `InputTooLarge`
  becomes a refused answer with the reason. A retryable provider error gets one retry.
- **Unknown column (before the tool phase).** If the question contains a dotted `model.column`
  whose model, seed or source exists but whose column does not, code refuses with
  "<model> has no column <col> (closest: a, b, c)". There are no LLM calls. Only real node names
  count, so CTE aliases (`order_agg.lifetime_value`), full unique_ids (`model.p.fct`) and file
  names (`fct.sql`) are never refused. Live (v0.2): the linker tied five `order_date` columns for
  "stg_orders.ship_date", and chain mode answered for one of them. **Since S08** the decision is
  `entity.dotted_column`, the one function the linker also uses (amendment C): a column part
  that maps through the abbreviation table alone to exactly one column of that model
  (`stg_payments.amt` → `amount_usd`) is not refused, and code puts "Interpreted
  stg_payments.amt as stg_payments.amount_usd." at the front of `answer_text`; 2+ columns are
  ambiguous; anything else is refused. A unit test pins that the loop refuses exactly when the
  linker has no match.
- **Evidence guarantee.** If the tool phase emitted no citable id (no `e_`/`s_`), code looks for
  exact, existing `model.column` ids in the question (at most 2). For each it runs
  `impact_downstream` when the wording is about effects (affect / impact / change / break /
  downstream), else `trace_upstream`. These are `code` steps, not LLM calls, and calls already in
  the log are skipped. The answer phase then runs normally. This generalises the earlier
  "no tool call" fallback. It was seen live in two shapes: no tool call at all (false premise),
  and tools called in the wrong direction (upstream of a seed, downstream of a leaf mart).
  The record's `stop_reason` gets `+code_evidence`.
- **Reachability fact (yes/no questions).** After the tool phase (and the evidence guarantee),
  if the question names **exactly 2** exact, existing `model.column` ids and has reachability
  wording (affect / impact / depend / feed / flow / reach / change), code runs the code-only
  `reachability` tool (not in the tool specs; an LLM call by that name gets `unknown_tool`).
  It checks the shortest directed path both ways on the **whole graph** and emits one citable
  fact `r_<8 hex>` plus the shortest path's edges (as normal `e_` ids). The direction asked is
  first-named → second-named, reversed for "depend" ("does Y depend on X" asks X → Y). The
  evidence line reads e.g. `r_…: raw_payments.amt does NOT reach dim_customers.lifetime_value
  (graph check)`. This is a `code` step, not an LLM call. One or three named columns make no
  fact, because there is then no single yes/no pair. The validator's R9 holds the answer's
  verdict to the fact (validator.md).
- **Linked evidence (rule `linked_evidence`, owner 17 Oct 2026).** After the tool phase and the
  evidence guarantee, if (a) the question asks where a column comes from or how it is computed
  (`comes from`, `upstream`, `derived`, `sourced`, `how is … computed/calculated/derived/built/
  made`) or what it affects (the evidence guarantee's effect wording, which wins), (b) every
  resolve_entity result is unambiguous and together they link **exactly one** column (the top
  candidate, a column), and (c) neither `trace_upstream` nor `impact_downstream` ran on that
  column, code runs the matching tool on it. It never fires for an `ambiguous: true` result,
  with no linked column, or for meaning questions ("what does X mean"), which have no lineage
  intent. Found by re-recording the presets after linker v2: with one clear candidate the 4B
  model sometimes stopped after resolve_entity (dev-14, then refused for lack of evidence) or
  read only the SQL (dev-13, no edges to cite). The evidence guarantee did not cover either,
  because it needs a dotted id in the question and fires only when nothing is citable. A
  `code` step, not an LLM call; `stop_reason` gets `+linked_evidence`.
- **Every code step is tagged.** Each code-initiated call carries `code_initiated: true` and its
  `rule` (`code_evidence`, `linked_evidence`, `reachability_fact`, `chain_trace`) in the ledger
  (`ToolResult`) and the run record (`StepResult`), so the v1.0 ablations can separate the
  model's tool choices from code's. The answer phase sees these results like any other.
- **No citable evidence after that**: refused by code with the tool errors as the reason, with
  no answer call.

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

**S12a (A4) additions.** `RunRecord.question_id` (set by a runner: `Agent.ask(question,
question_id)`) and `RunRecord.cache`: `hit` when every LLM call came from the response cache,
`miss` when none did, `partial` otherwise, null when the run made no LLM call. Both are additive;
`SCHEMA_VERSION` stays 1 and old records load. The benchmark runner is `eval/systems/s4.py`
(see `eval-dev.md`); the CLI and UI still log through `RunLogger`.

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
S12a (A1):
- A. "Where does fct.total come from?" and the model's draft lists two
  `clarification_candidates`. Does the user get a clarification? Which of the three ignore
  conditions applies, and where can you still see what the model proposed?
- B. Someone edits S1's frozen system prompt to fix a typo in the "confidence" line. Which test
  fails, and why does the S4 prompt not silently follow? What would S12b have to do to add an
  S4-only line legitimately?
- C. Why is the S4 text a literal copy checked by a test rather than an import of `S1_SYSTEM`?

S12a (A6):
- F. dev-67's answer prompt is trimmed and its first draft fails R2 on 12 ids. How many failure
  lines does the regenerate show, in what order, and what happens if not even one fits?
- G. Why is `REGENERATE_RESERVE` the max of the repair and regenerate turns rather than their
  sum, and why was a worst-case reserve rejected?

S12a (A4, A5):
- D. A run makes 4 LLM calls; 3 come from the cache. What is the record's `cache` value, and why
  does M15 need it at record level?
- E. dev-67's answer prompt is over the cap and `trim()` cuts 6 indirect columns of
  `fct_orders`. What does the model read about them, and why is the line counted inside the
  budget check?

Earlier:
1. The tool phase compacted a `get_model_sql` result down to its `excerpt_id` and range. Why can
   the answer phase still quote the SQL, and why would that be impossible in a single-phase loop
   that answers from its own history?
2. "Where does refunds amount come from?" ties four candidates on synthetic_shop (all rewritten
   matches, 0.87) and gets no clarification. Walk through the policy: which candidate is answered for, who made the extra
   tool call, and why it does not count toward the 8-call cap.
3. In the live smoke, question b cited `e_4b2_403a`, an id no tool emitted. Which part of this
   design guarantees the id gets no citation, and which part (not yet written) must remove the
   claim? What would `draft_raw` in the run record let you measure later?
4. "How is int_order_financials.order_total computed?": the model calls resolve_entity, then
   get_model_sql, and answers. Does `linked_evidence` fire, and why doesn't the evidence
   guarantee? Would it fire for "What does order_total mean?", or if resolve_entity had said
   `ambiguous: true`? How would an ablation count the extra trace: as the model's call or not?
5. A yes/no answer says "No, X does not reach Y" in prose, but `reach_verdict` is null. How does
   metrics score it, and why? In S12, R9 salvage replaces the LLM's "yes" with code's "no": what
   do `reach_verdict` and `reach_verdict_source` hold, and which S4 view counts that verdict?
6. (S12b, B3) A claim cites a miscopied id and also skips a hop. Which `origin` does it end with,
   and why does the order R2r → R8c make that the only possible answer? Which view of metrics
   counts it?
7. (S12b, B3) Why is `premise_corrected` not given a source field like `reach_verdict`, and what
   would have to change in the code before one were needed?
8. (S12b, B3) S4's draft schema is no longer byte-equal to S1's. What exactly does the parity
   test now assert, and which edit to S4's schema would still fail it?
9. (S12b, B4) The same question runs with and without a search index. Which prompts, specs and
   cache keys differ between the two runs, and why is the answer prompt the same in both?
10. (S12b, B1) An impact payload was cut at 40 of 62 columns, and the answer names 10. How many
    columns does G1 add, from where, and why can those claims cite edges the model never saw?
11. (S12b, B1) Why does a trace input count as covered when its edge is cited even if the answer
    never writes its id, and which metrics view would change if that rule were dropped?

12. (S12b, B2/B5) Why does `interpretation` count in S4-raw while a code-set `reach_verdict`
    does not? Point to where each is set relative to the LLM's answer call.
13. (S12b, B6) "Is total in fct star downstream of amt in raw?" with two resolve_entity calls:
    which columns does the fact use, in which direction, and what changes if the model calls the
    two resolves in the other order?
14. (S12b, B6) Why must "orders daily" not count as naming `orders`, and how does the matcher
    prevent it?

15. (S12b, B7) A tie of 3 unrelated columns, and the model stops after resolve_entity. How many
    LLM calls and code steps does the run take, and what does it return if none of the traces
    finds an edge?
