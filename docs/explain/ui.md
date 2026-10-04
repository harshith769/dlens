# Explain: local UI (`src/dlens/ui/`)

## What it does
`make ui` starts a Streamlit app on the local Ollama model. Nothing in it calls a cloud provider.

**Header:** the title, a project picker (`synthetic_shop`, `jaffle_shop`, or `?project=` in the
URL), the stats `models · columns · edges · parse coverage` (FULL models / models in the parse
report), and a provider slot. The slot says "Local model (Ollama)". It can also show
"x of N left today" (only for a quota-limited provider, so never for now) and "cached" (only when
every LLM call of the answer on screen was a cache hit).

**Tabs:**

| Tab | Shows |
|---|---|
| Ask | Left 30%: question box, Ask, this session's history (click to restore), and examples grouped by kind with a one-line hint. Examples are dev questions that passed in `eval/reports/dev_r9.json`. Right 70%: verdict badge + verification badge, the answer, claims with ✓/⚠ and citation chips, removed claims, Markdown/JSON download, then detail tabs Lineage, Source, Steps and Checks. |
| Explore lineage | No LLM. A searchable `model.column` picker, direction (upstream/downstream/both) and a depth slider. Shows the lineage diagram, an edge table (from, to, kind, expression, checked `file:line`) and the SQL of any model shown. |
| How it works | The pipeline (question → tools → evidence → answer → validator → cited answer), the nine rules in one sentence each, and the current dev score. The score is labeled "Dev set: 20 hand-written questions (not the benchmark)" with the report's commit date. |

**Badges.**
- **Verdict** comes from real fields only. It is *Refused* (`answer.refused`), *Clarification*
  (`answer.clarification`), *Chain mode* (`record.ambiguity.mode == "chain"`) or *Answered*.
  Corrected-premise badge deferred until the agent emits a real signal (ADR candidate for v0.3).
- **Verification** comes from `record.validation`. It is *Verified*; *Repaired n* / *Completed n* /
  *Regenerated* (still verified, with what code or the second draft fixed); *Partially removed*
  (salvaged); *Nothing verifiable* (the validator refused); or *Not checked* (refusal or
  clarification).
- **Per claim:** ✓ verified as drafted. ⚠ repaired id (R2r) or completed citations (R8c). Claims the
  validator dropped are listed with the rules they failed.

**Lineage diagram** (`view.build_lineage_dot`):
- Graphviz DOT with `rankdir=LR` and one cluster per layer. The layer comes from the resource type
  (source, seed), then the folder (`staging/`, `intermediate/`, `marts/`), then the name prefix
  (`stg_`, `int_`, `fct_`/`dim_`), else "Models".
- Each model is an HTML-table node with one port per relevant column. Edges run port to port,
  colored by kind, with the expression clipped to 30 characters as the label (identity edges have
  no label).
- The asked-about column has a bold border, the selected citation's edge is drawn thick, and a
  legend explains the kinds. Edge-kind colors appear only here and in its legend.
- The Ask toggle switches between "Cited edges" (`answer.subgraph`) and "Full lineage of the
  column": every edge within 10 hops, nearest first, capped at 40 with a note.

## How it works
- **Three files.** `app.py` is layout only. `view.py` holds pure helpers and does not import
  Streamlit. `style.py` holds the design tokens, the one CSS block, and tiny HTML builders that
  escape their input. Colors and fonts are in `.streamlit/config.toml`: IBM Plex Sans / Mono load
  through the theme `font` / `codeFont` options, which take Google Fonts URLs in Streamlit 1.65.
- **Graph and state.** The graph is built once per project with `st.cache_resource`. Each answer
  keeps its own `Toolbox` in `st.session_state` (history included), so restoring an old answer
  also restores its ledger (needed for `r_` graph-check text).
- **Stateful tabs.** The detail tabs are `st.tabs(..., key="detail", on_change="rerun")`, so a
  chip click can open the Source tab by setting `session_state.detail`.
- **Where data comes from.** Everything shown is derived from the run record, the answer, the
  ledger or the graph. The UI never decides whether a claim is true.
- **Source view.** Pygments highlights the SQL (`HtmlFormatter(nowrap=True)` closes its spans at
  each line end). `view.highlight_sql` then adds line numbers and marks the cited range; without
  Pygments the lines are only escaped.
- **Safety.** Every file read goes through `provenance.safe_read`, which refuses paths outside the
  project. Every string rendered with `unsafe_allow_html` is escaped first, and tests cover
  `<script>`. Exports contain only project-relative paths: no log path, no project folder.
- **Errors.**
  - A provider failure becomes a refusal in the agent; the UI recognizes it (`view.error_hint`) and
    shows an error state with the exact fix (`ollama serve`, `ollama pull <model>`, or
    `uv sync --extra agent --extra ui`).
  - An unknown project or a missing corpus folder shows `make ingest CORPUS=<name>`.

## Why this design
- **No business logic in the UI.** A wrong answer can only be a loop or validator bug, never a UI
  bug, and every helper is unit-tested without a browser.
- **The diagram is column-level.** A model-level graph cannot show *which* column feeds which, and
  that is the whole product.
- **Explore uses the graph directly.** Browsing lineage is instant and costs no quota, which
  matters once a cloud provider with a daily budget is plugged in.

## Alternatives rejected
- **Programmatic tab switching through a radio row.** Streamlit 1.65's stateful `st.tabs` does it
  natively.
- **`st.code` for the source.** It has no line highlight; the old UI repeated the cited lines in a
  second block.
- **Mermaid or vis.js for the diagram.** That would add a JS dependency; Graphviz renders in the
  browser through `st.graphviz_chart`, with no system binary.
- **A "Corrected premise" verdict from a text heuristic.** It would be a guess the validator never
  checked.

## Explain-back questions
1. Why does `removed_claims` pick the validation round that keeps more claims, and what would show
   the wrong claim texts if it always used the first draft?
2. Why is the provider slot filled twice per rerun, and what would "cached" describe if it were
   filled only once in `header()`?
3. Which three defenses keep a hostile string in a model name, an expression or the answer from
   running as HTML, and where is each tested?

(Not a core module in CLAUDE.md's sense: no lineage, metrics, scorer or validator code changed.)
