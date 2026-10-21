# Explain: agent tools (`src/dlens/agent/tools/`)

Covers the four v0.2 tools, the provenance contract the validator depends on, and `resolve_entity`
(the v1 entity-linker scorer; v2 in v0.3 replaces its scoring).

## What it does
`Toolbox(graph, project_dir)` runs four deterministic tools for the agent:

| Tool | Returns to the LLM |
|---|---|
| `resolve_entity(text, k=5)` | ranked candidate columns and models, each with a score and a match tier |
| `trace_upstream(column_id, max_depth=10, include_indirect=False)` | paths, each a list of one-line edge strings (indirect hops print `e_…: a -> b [JOIN]`) |
| `impact_downstream(column_id, max_depth=10, include_indirect=True)` | columns grouped by (depth, kind) as `"model.column e_…"` (the via edge), "+K more" lines if cut, affected models and exposures |
| `get_model_sql(model_id, around_column=None)` | numbered lines of the SOURCE `.sql` as ordered windows (`…` between gaps), one `excerpt_id` per window |

**Specs shown to the LLM are trimmed** (437 estimated tokens for all four, down from 728) because
they ride on every tool-phase call under the 3K cap. They advertise only `text`, `column_id`,
`max_depth`, `model_id` and `around_column`. The tools still accept `k` and `include_indirect` with
the defaults above, so the spec §8 signatures are unchanged. Since S12a (s12-design A5.1 (i), ADR
0026) the defaults are honoured: trace is direct, impact direct + indirect. The flag is still not
advertised: it would cost ~30 tokens on every tool call and leave a 4B model to pick the mode per
question; which tool is called decides the mode. `toolbox.edge_string(eid)` gives
the agent the same compact line for any edge id when it rebuilds the answer prompt.

`toolbox.call(name, args)` never raises. Bad input comes back as `{"error": {"code", "message",
"suggestions"}}` (codes: `unknown_column`, `unknown_model`, `ambiguous`, `invalid_argument`,
`not_sql`, `unknown_tool`) so a small model can correct itself.

## Two outputs per call: the LLM payload and the side record
Each call returns a `ToolResult {tool, args, llm_payload, side_records}`.
- **`llm_payload`** is what the model sees. It holds compact strings and ids only, e.g.
  `e_1a2b3c4d: stg_orders.amount -> orders.amount [RENAME]`. TRANSFORMATION and AGGREGATION edges
  also show the expression cut to 60 characters (`[AGGREGATION: sum(amount)]`) so the model can say
  how a value is computed. It is capped at 1,500 estimated tokens (the same `estimate_tokens`
  used for the 3K input cap, measured on the exact tool message).
- **`side_records`** holds the full edge objects (`from`, `to`, `kind`, expression, confidence and a
  citation) and column citations. Code, the validator and the UI use them. The LLM never types a
  file name or a line number: it copies `edge_id`s, and code attaches the citation.
`Toolbox.log` keeps every call as `{tool, args, llm_payload, side_records}`, so both "what the
model saw" and "what the citations were" are preserved for the no-validator ablation.

## The provenance contract (what the validator relies on)
- **`edge_id`** = `"e_" + sha1("from_column|to_column|kind")[:8]`, on full lower-case column ids and
  the kind's string value. It depends only on the edge's content, so the same graph gives the same
  ids on any run or machine. `Provenance` raises if two different edges collide.
- **`excerpt_id`** = `"s_" + sha1("file|line_start|line_end")[:8]`, one per line window
  `get_model_sql` actually returned (after truncation); every window id goes into the ledger. Claims put edge ids and excerpt ids in the same
  `chunk_ids`-style slot; v0.3 chunks will use it too.
- **Citation** = `{file, line_start, line_end, level}`. `file` is the SOURCE `.sql` relative to the
  project root. Levels:
  - `line`: the range contains the column name as a whole word.
  - `star`: the range holds the `*` that produced the column; the name is not written in the file.
    **Validator rule 3 for `star`: check that the range contains `*`, not the column name.**
  - `model`: the locator found nothing; the whole file is cited and no line is claimed. Seed
    columns always get this (the file is the CSV, whose header holds the name).
  - For an `s_` excerpt id the citation level is `line`, and rule 3 only needs the file and range
    to exist (the excerpt may legitimately not contain any one column). Each excerpt side record
    also stores `text_sha1` (sha1 of the window's lines), so the validator can detect a file
    edited after the tool ran.
- **`safe_read(root, file)`** is the one path-traversal-safe file reader (`../` and symlink
  escapes return None). `Provenance` caches it per conversation; the validator calls it fresh.
- Every citation is re-checked against the file text before it leaves `provenance.py`. If the
  located range lacks the name (and has no `*`) it is downgraded to `model`.
- **Ledger.** `toolbox.emitted_ids` is the set of edge and excerpt ids the LLM was shown in this
  conversation (only ids that survived truncation); `toolbox.record(id)` returns the full record.
  It is per conversation: use one `Toolbox` per question or call `reset()` between questions.

## How the locator works (and why it is not new code)
Edges already carry `file`, `lines` and `model_level_citation`, computed by
`lineage/provenance.py:locate()`: a depth-aware scanner over the source file that splits every
SELECT list into items and skips strings, comments and Jinja. The tools import it and, for columns
with no edge to carry a citation, call it directly. They add only the re-check described above.
Compiled SQL is never cited because Jinja changes line numbers.
On `synthetic_shop` (132 columns): 88 `line`, 14 `star`, 30 `model` (exactly the 30 seed columns).
Every one of the 100+ edges cites a `line` or `star` range inside `models/`.

## Truncation
`largest_fit` binary-searches the largest prefix of the result items (paths, impact columns, SQL
lines) whose payload is within the cap. Items are in graph order, so which ones survive is
deterministic. The payload then says `truncated: true` and `dropped: {paths|columns|lines: n}`, and
side records and the ledger are built only from what was kept, so no id is ever emitted that the
model did not see. Models and exposures are dropped last.

## `get_model_sql` and alias windows

**Leniency.** A `model.column` passed as `model_id` (seen live from the 4B model) is split into
the model and `around_column`, but only when the whole text is not itself a model and
`around_column` is empty. If the model part is unknown, the original `unknown_model` error is
returned for the original text.

Without `around_column`, the excerpt is the whole file as one window. With it, the excerpt starts
from the column's located lines (+/- 3 context). Then, up to 3 hops, it adds the **earlier lines
in the same file that define aliases the expression reads**. An identifier counts if it is not a
qualifier (`order_agg.` is skipped, `lifetime_value` is followed). A definition is the nearest
earlier line with `as <identifier>` that is not a CTE header (`x as (`). A definition that spans
several lines (`case … end as x`) is followed upward to the start of its select item.

On `dim_customers.lifetime_value` the excerpt becomes line 7 (`sum(items_subtotal + sales_tax -
refunded_amount) as lifetime_value`, where it is computed) plus lines 18–24 (the final
`coalesce`), not the final select alone. Windows are ordered by line and merged when adjacent,
and the flat `excerpt` puts `…` between gaps. Under the 1,500-token cap, the deepest alias
windows are dropped first (`dropped.windows`), then the remaining window's tail is cut. This is
text search, not a parser: it can only add context lines. Ids and edges still come from the
graph. On both corpora every model column gives at most 2 windows and at most 321 tokens.

## `resolve_entity`
Linker v2 (S08). The full design, the evidence and the explain-back questions are in
[linker.md](linker.md). In short: stage 1 exact (id / model name 1.00, literal column name 0.97,
always ranked first); stage 2 normalised (surface 0.93, rewritten 0.87 via plural, abbreviations,
phrase rules, weak `usd`, word order; fuzzy ≤ 0.80), plus a model-named-in-the-text bonus and a
small layer prior; stage 3 hybrid over column cards, only when stage 2 is not confident and the
toolbox has a search index. Nothing below 0.60 is a candidate. `ambiguous: true` when the top
two are within 0.05. The payload shape is v1's plus an optional `hybrid` key (ADR 0022). Score
parts and `closest` stay in the side record.

## Why this design
- Out-of-band side records keep the 1,500-token budget for what the model reads, while the validator
  gets exact citations; logging both keeps drafts replayable.
- Content-derived ids make citations reproducible and testable across builds.
- Re-checking each citation means "never invent a line" is enforced where the citation is built.
- Structured errors with suggestions let a 4B model recover instead of the loop crashing.

## Alternatives rejected
- A second source-line locator inside the tools: two scanners would drift apart.
- Inline edge objects (with citations) in the payload: they roughly halve how many paths fit.
- Sequential or random edge ids: they change between builds and break caching and replays.
- Embeddings for `resolve_entity` in the core install: the hybrid stage needs the `retrieval`
  extra and a built index, so the core and demo installs run stages 1-2 only (linker.md).
- `rapidfuzz`: a new dependency for a corpus this small.

## Indirect edges in the tools (S12a, ADR 0026)
- **Ids and records.** `Provenance` registers indirect edges too; `edge_id` is the same formula
  (the indirect kinds JOIN, FILTER, … differ from the direct kinds, and the collision check
  still runs). An indirect edge's record adds `key` (the clause key) and `indirect: true`; direct
  records are byte-unchanged. `common.hop()` replaces `direct()`.
- **Citations by kind.** A direct edge's cited lines must name its `to` column. An indirect
  edge's must name its `from` column (the key), or its clause key `rel.col` where `rel` is a CTE
  or a derived alias used as a qualifier (`relation_names`, the metrics M7 (iv-k+) guard, copied,
  not imported). Otherwise the whole file (`model`). Never `star`. On synthetic_shop all 621
  indirect edges cite at `line`: 598 by the from column, 23 by the guarded key, and metrics M7
  accepts all 621 (checked offline, 20 Oct 2026).
- **Impact payload shape B** (owner, 20 Oct 2026): full dotted ids, one via edge id each,
  grouped `"<depth> [<kind>]"`. A column is `[direct]` only if an all-direct path reaches it, at its
  direct depth (a second, direct-only traversal decides this: decision A5-IMPACT-DIRECT-LABEL).
  Otherwise its label is the kind of the first indirect hop on its shortest path, and its depth is
  that path's length; a column reachable both ways appears once, under `[direct]`. Why full ids:
  the model copies what it reads, and only `model.column` ids count for metrics M3 and can be
  checked by R4. Every dev impact payload fits the 1,500-token cap uncut (1,114–1,462 measured).
- **Over the cap** columns are cut in a fixed order (depth, model, column), kept from the front,
  and every cut (depth, kind, model) gets one line in `more`: "+K more columns in <model>
  (<kind>)", with `truncated` and `dropped`. When that would be more than 12 lines (a wide project
  where each cut model loses one column, so the lines would be as long as what they replace) the
  lines are per (depth, kind), stating both counts: "+K more columns in M models (<kind>)". Only
  `stg_products.product_id` (175 columns, in no dev question) is cut on synthetic_shop.
- **Side records.** `edges` and `columns` hold the shown columns (what the ledger emits and the
  validator's evidence reads); `full` holds every reached column with its whole via chain and
  every chain edge's record, for code (G1, S12b). The model never sees `full`.
- **The `r_` fact** (`reach.py`) decides its verdict over direct + indirect hops and states the
  direct reading too ("… in 1 hop (graph check: with indirect dependencies; not through direct
  edges)"); the direct reading is the shortest DERIVES-only path (decision A5-R9-DIRECT-READING).

## `search_docs` in S4 (S12b, B4)
- **What:** with a search index open, the Toolbox advertises a fifth tool, `search_docs(query)`
  (`specs.SEARCH_DOCS_SPEC`), and runs `tools/search.py` for it. Without an index (the demo
  install) the specs are `TOOL_SPECS` exactly and a call by that name gets `unknown_tool`.
- **How:** each shown hit's `id` (`c_…`) is read by `_ids_in` (`hits[].id`) and enters the
  ledger with its side record (`side["chunks"]`, citation from `chunk_citation`, A3). Hits cut by
  the 1,500-token cap are not shown, so they never enter the ledger. The tool prompt gains one
  sentence only with an index (`prompts.tool_system(docs)`), and the budget manager has a
  `search_docs` digest (level 1: id, kind, title, file, lines; level 2: id, kind, title), so
  compaction keeps every hit id.
- **Why:** Ask questions and the stale-doc trap need project text that the lineage tools don't
  return. Advertising the tool only with an index keeps the demo's prompts, specs and cache keys
  unchanged. The import of `dlens.retrieval` stays lazy (inside `call`).
- **Cost:** the tool-phase fixed cost (system prompt + specs) goes 721 → 850 est. tokens (+129)
  on every tool-phase call when an index is open (`test_tool_phase_growth_per_call`).
- **Rejected:** advertising it always and failing with `no_index` (the demo would pay the tokens
  for a tool it can't run); a separate `linker_hybrid` switch (s12-design B4 (b)).

## Explain-back questions (for you)
S12a (A5):
- A. `raw.id -> stg.x_id` (direct) `-> fct.total` (JOIN) `-> fct_star.total` (direct): under which
  group key does each reached column appear in `impact_downstream(raw.id)`, and why is
  fct_star.total not `[direct]` although its last hop is direct?
- B. An indirect edge's cited line says `where orders.customer_id > 0` and the edge's from column
  is `cust_ref`. Is the citation `line` or `model`, and what would change if `orders` were a table
  alias rather than a CTE?
- C. A payload is cut. Where does the model see that columns are missing, and where can code still
  find them?

1. Why is `kind` part of the `edge_id` hash while the file, lines and expression are not? What would
   break in the validator if an edge's line moved but its id changed?
2. A column's name does not appear in its model's source file (a `SELECT *`, or an alias built in
   Jinja). Why does the tool cite `star` or `model` instead of the nearest plausible line, and what
   does validator rule 3 check in each case?
3. Why does the LLM copy `edge_id`s instead of writing file and line citations itself, and which
   failure in a 4B model does that remove?
4. Why are the LLM payload and the side record logged separately, and which later experiment would
   be impossible if only one of them were kept?
5. (S12b, B4) A search_docs call returns 20 hits but the payload keeps 9. Which ids can the model
   cite, which ones does the ledger know, and what would R2 say about hit 12?
6. (S12b, B4) Why does the demo install's tool prompt keep its hash after B4, and which test
   would fail if `search_docs` were always advertised?
7. (S12b, B4) A tool history with three search_docs results goes over the cap. What does the
   level-2 digest keep, and why is that enough for the answer phase?
