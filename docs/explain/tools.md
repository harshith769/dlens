# Explain: agent tools (`src/dlens/agent/tools/`)

Covers the four v0.2 tools, the provenance contract the validator depends on, and `resolve_entity`
(the v1 entity-linker scorer; v2 in v0.3 replaces its scoring).

## What it does
`Toolbox(graph, project_dir)` runs four deterministic tools for the agent:

| Tool | Returns to the LLM |
|---|---|
| `resolve_entity(text, k=5)` | ranked candidate columns and models, each with a score and a match tier |
| `trace_upstream(column_id, max_depth=10, include_indirect=False)` | paths, each a list of one-line edge strings |
| `impact_downstream(column_id, max_depth=10, include_indirect=True)` | columns by depth as `{id, via: edge_id}`, affected models and exposures |
| `get_model_sql(model_id, around_column=None)` | numbered lines of the SOURCE `.sql` as ordered windows (`…` between gaps), one `excerpt_id` per window |

**Specs shown to the LLM are trimmed** (425 estimated tokens for all four, down from 728) because
they ride on every tool-phase call under the 3K cap. They advertise only `text`, `column_id`,
`max_depth`, `model_id` and `around_column`. The tools still accept `k` and `include_indirect` with
the defaults above, so the spec §8 signatures are unchanged. Indirect edges are not in the graph
yet, so advertising `include_indirect` only invited useless calls. `toolbox.edge_string(eid)` gives
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
Tiers, strongest first: exact id or model name (1.00), literal column name (0.97), normalised column
name (0.93), fuzzy (< 0.90: soft token overlap plus `difflib` ratio over model and column tokens).
Normalising lower-cases, splits on `_ . space` and camelCase, strips a plural `s`, maps abbreviations
(`amt→amount`, `qty→quantity`, ...) and ignores `usd` when comparing. Ties break non-seed first,
then by id, and `ambiguous: true` is set when the top two scores are within 0.05.
Literal and normalised matches are separate tiers on purpose: `refund_amt`, `refund_amount` and
`refunded_amount` are near-duplicates of different grain (trap `near_duplicate_names`) and must not
collapse into one candidate.

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
- Embeddings for `resolve_entity`: v0.3 adds hybrid search; v1 must be deterministic and
  dependency-free.
- `rapidfuzz`: a new dependency for a corpus this small.

## Explain-back questions (for you)
1. Why is `kind` part of the `edge_id` hash while the file, lines and expression are not? What would
   break in the validator if an edge's line moved but its id changed?
2. A column's name does not appear in its model's source file (a `SELECT *`, or an alias built in
   Jinja). Why does the tool cite `star` or `model` instead of the nearest plausible line, and what
   does validator rule 3 check in each case?
3. Why does the LLM copy `edge_id`s instead of writing file and line citations itself, and which
   failure in a 4B model does that remove?
4. Why are the LLM payload and the side record logged separately, and which later experiment would
   be impossible if only one of them were kept?
