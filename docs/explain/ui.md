# Explain: local UI (`src/dlens/ui/`)

## What it does
`make ui` starts a Streamlit app on the local Ollama model. Nothing in it calls a cloud provider.

**Header:** the title, a one-line intro and a GitHub link, the provider on the right, then a
project picker (`synthetic_shop`, `jaffle_shop`, or `?project=` in the URL) and the stats
`models · columns · edges · parse coverage` (FULL models / models in the parse report). The
provider slot says "Local model (Ollama)" and can add "x of N left today" (only for a
quota-limited provider, so never for now). Whether an answer was cached is a badge on the answer.

**Tabs:**

| Tab | Shows |
|---|---|
| Ask | Left 30%: question box, Ask, this session's history (`view.push_history`: one entry per question and project, latest kept, newest first, at most 8; a verdict-colored dot and the question on one line), and examples as buttons under their group heading (the hint is the heading's tooltip). Examples are dev questions that passed in `eval/reports/dev_r9.json`. Right 70%: verdict, verification and (if every LLM call was a cache hit) "Cached" badges, the answer, claims with ✓/⚠ and clickable mono citation chips, removed claims, detail tabs Lineage, Source, Steps and Checks, then small Markdown/JSON download buttons. |
| Explore lineage | No LLM. A searchable `model.column` picker, direction (upstream/downstream/both) and a depth slider. Shows the lineage diagram, an edge table (from, to, kind, expression, checked `file:line`) and the SQL of any model shown. |
| How it works | The pipeline (question → tools → evidence → answer → validator → cited answer), the nine rules in one sentence each, and the current dev score. The score is labeled "Dev set: 20 hand-written questions (not the benchmark)" with the report's commit date. |

**Badges.**
- **Verdict** comes from real fields only. It is *Refused* (`answer.refused`), *Clarification*
  (`answer.clarification`), *Chain mode* (`record.ambiguity.mode == "chain"`) or *Answered*.
  Corrected-premise badge deferred until the agent emits a real signal (ADR candidate for v0.3).
- **Verification** comes from `record.validation`. It is *Verified*; *Repaired n* / *Completed n* /
  *Regenerated* (still verified, with what code or the second draft fixed); *Partially removed*
  (salvaged); *Nothing verifiable* (the validator refused); or *Not checked* (refusal or
  clarification). Each badge has a one-sentence tooltip (`Badge.help`).
- **Per claim:** ✓ for every kept claim, since all of them passed the rules; a grey note says what
  code fixed first: "id auto-corrected" (R2r) or "missing hop added" (R8c). ⚠ is kept for anything
  else. Claims the validator dropped are listed with the rules they failed.

**Lineage diagram** (`view.build_lineage_dot`):
- Graphviz DOT with `rankdir=LR` and one cluster per layer. The layer comes from the resource type
  (source, seed), then the folder (`staging/`, `intermediate/`, `marts/`), then the name prefix
  (`stg_`, `int_`, `fct_`/`dim_`), else "Models".
- Each model is an HTML-table node with one port per relevant column. Edges run port to port,
  colored by kind, with the expression clipped to 30 characters as the label (identity edges have
  no label).
- The asked-about column has a bold border and the selected citation's edge is drawn thick. A
  small HTML legend above the chart lists only the kinds drawn (`LineageDot.kinds`). Edge-kind
  colors appear only here and in that legend.
- Every node, cluster and edge has a `tooltip`, so a hover never shows Graphviz's internal names
  (`m1:c3:e->m0:c1:w`). Fewer than 6 models: drawn at natural size, not stretched. Text is Arial
  12/11pt because Graphviz sizes boxes from font metrics it knows; IBM Plex overflowed them.
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
- **Source view.** Pygments highlights dbt SQL with the `sql+jinja` lexer, so `{{ ref() }}` is a
  template tag rather than an error token (`HtmlFormatter(nowrap=True)` closes its spans at each
  line end). `view.highlight_sql` then adds a line-number gutter and marks the cited range; token
  colors come from `view.source_css()`. It is shown with `st.html`, not `st.markdown`: the
  Markdown pass collapsed the newlines inside `<pre>`.
- **Pinned Streamlit.** The custom CSS targets Streamlit 1.65 internals (`stTab`,
  `st-key-<key>` classes of keyed containers), so the `ui` extra pins `streamlit>=1.65,<1.66`.
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
- **Graphviz for the How-it-works pipeline.** It scaled six boxes down to unreadable text at
  900 px and its loop label overlapped the edges; wrapping HTML steps stay readable at any width.
- **Mermaid or vis.js for the diagram.** That would add a JS dependency; Graphviz renders in the
  browser through `st.graphviz_chart`, with no system binary.
- **A "Corrected premise" verdict from a text heuristic.** It would be a guess the validator never
  checked.

## Explain-back questions
1. Why does `removed_claims` pick the validation round that keeps more claims, and what would show
   the wrong claim texts if it always used the first draft?
2. Why is "cached" a badge on the answer rather than in the header, and what would a header
   "cached" describe after you restore an older answer from the history?
3. Which three defenses keep a hostile string in a model name, an expression or the answer from
   running as HTML, and where is each tested?

(Not a core module in CLAUDE.md's sense: no lineage, metrics, scorer or validator code changed.)
