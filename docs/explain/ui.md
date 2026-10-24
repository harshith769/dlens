# Explain: local UI (`src/dlens/ui/`)

## What it does
`make ui` starts a Streamlit app on the local Ollama model over the bundled corpora; nothing in
that mode calls a cloud provider. `dlens ui --project DIR` is the same app in project mode on a
user's ingested project (below), where Ask can use a cloud provider only if the user configures
one with their own key. The public demo is the same app in demo mode (prebuilt bundle, Gemini behind caps, replayed
presets): see `docs/explain/deploy.md`.

**Header:** the title, a one-line intro and a GitHub link, the provider on the right, then a
project picker (`synthetic_shop`, `jaffle_shop`, or `?project=` in the URL) and the stats
`models · columns · edges · parse coverage` (FULL models / models in the parse report). The
provider slot says "Local model (Ollama)" and can add "x of N left today" (only for a
quota-limited provider, so never for now). Whether an answer was cached is a badge on the answer.

**Tabs:**

| Tab | Shows |
|---|---|
| Ask | Left 30%: question box, Ask, this session's history (`view.push_history`: one entry per question and project, latest kept, newest first, at most 8; a verdict-colored dot and the question on one line, clipped in the middle so questions with the same start stay distinct; the tooltip has the full question), and examples as buttons under their group heading (the hint is the heading's tooltip). Examples are dev questions that passed in `eval/reports/dev_r9.json`. They are grouped by subtype (`view._GROUPS`). The groups list both the v0.2 subtype names and the S09 re-tags (`yesno`, `ambiguous`, `dotted_near_miss`, …), so the 96-question dev file shows the same examples as before. Right 70%: verdict, verification and (if every LLM call was a cache hit) "Cached" badges, the answer, claims with ✓/⚠ and clickable mono citation chips, removed claims, detail tabs Lineage, Source, Steps and Checks, then small Markdown/JSON download buttons. |
| Explore lineage | No LLM. A searchable `model.column` picker, direction (upstream/downstream/both) and a depth slider. Shows the lineage diagram, an edge table (from, to, kind, expression, checked `file:line`) and the SQL of any model shown. |
| How it works | The pipeline (question → tools → evidence → answer → validator → cited answer), the nine rules in one sentence each, and the current dev score. The score is labeled "Dev set: 20 hand-written questions, local qwen3:4b (not the benchmark)" with the report's commit date. |

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

## Project mode: `dlens ui --project DIR` (S14, E2)
The same app on **one** project ingested with `dlens ingest --artifacts`. `dlens ui` sets
`DLENS_UI_PROJECT` / `DLENS_UI_TARGET` (and drops `DLENS_DEMO`). `app.py` then calls
`project_main()` instead of the corpora/demo layout. The pure helpers are in
`src/dlens/ui/project.py`.

| Tab | Shows (LLM?) |
|---|---|
| Explore | Models parsed and FULL / PARTIAL / TABLE_ONLY / FAILED counts (`coverage_summary`, the levels `dlens ingest` prints), a model table worst first with the reasons, and the columns of a picked model with in/out edge counts. No LLM. |
| Trace / Impact | A column, a direction, a depth: the lineage diagram and edge table of *Explore lineage*, then the paths exactly as `dlens trace` / `dlens impact` print them (`render_trace` / `render_impact`, optionally with indirect edges), and the equivalent CLI command. No LLM. |
| Source | Read-only. The file picker lists only `graph_files(graph)`, the files the graph names. Each file is read through `safe_read` (inside the project; package symlinks only for graph files), and the compiled SQL comes from `target/compiled/<package>/…`. No LLM. |
| Ask | The Ask tab above, plus a provider panel and, under it, whether docs search is on. Examples are computed from the graph (end columns to trace, start columns to impact). |
| How it works | The pipeline and the nine rules. Instead of the dev score (which is about the corpora) it says which tabs call a model. |

The privacy line "Your code stays on this machine unless you configure a cloud provider." is
rendered under the header *before* the graph loads, so it is on every page, including the
not-ingested one.

- **Loading.** `project.load` never builds a graph: it uses `load_artifact_cache`. With no
  `manifest.json` it says `dbt compile && dbt docs generate`, then `dlens ingest --artifacts
  <target>`. With a missing or stale cache it says the `dlens ingest` command. The CLI prints
  the same hint and exits 2 before starting Streamlit.
- **Launch.** `python -m streamlit run <dlens/ui/app.py>` with `--server.address 127.0.0.1
  --server.headless true --browser.gatherUsageStats false`. `--host` binds elsewhere and prints
  a warning. `dlens ui` without Streamlit prints `pipx install "dlens-lineage[ui]"` /
  `pip install "dlens-lineage[ui]"`; the check is a `find_spec`, and the import of `dlens.ui.*`
  comes after it.
- **Same agent as S4.** Ask calls `loop.ask` with `Toolbox(graph, project_dir, index)`, which is
  exactly S4's construction. The index (`target/dlens/index`, built by `dlens search
  --artifacts`) is opened only when the retrieval extra is importable. Without it, Ask runs on
  the graph tools only (S4 with hybrid off) and the panel says so with the command.
- **Missing extras.** Ask checks `find_spec` for the provider's library (`ollama`,
  `google.genai` + `httpx`, `httpx`) before building a client, and shows the install command.
  Nothing on the Explore / Trace / Source path imports them. A test runs the whole app in a
  subprocess with ollama, google.genai, httpx, bm25s, onnxruntime and tokenizers blocked.

### Keys and isolation from the benchmark
- **Where a key comes from.** Either the password box, which is an *unkeyed* widget so its value
  is never in `st.session_state.to_dict()`, or an environment variable whose **name** the user
  types; the panel shows the name, never the value. `GEMINI_API_KEY` or any other ambient key is
  never read. The value is wrapped in `Secret` (masked `repr`/`str`, not picklable) and lives
  only for one `_ask_local` call.
- **A fresh env per ask.** `provider_env` builds the mapping for `make_client` from scratch:
  provider, model, base URL, daily budget, the key, and `DLENS_CACHE_DIR` /
  `DLENS_STATE_DIR` / `DLENS_RUN_DIR` under `<target>/dlens/ui/`. It never copies
  `os.environ` and never writes to it. So the UI's LLM cache, quota counter and run logs never
  touch `eval/cache`, the eval quota file or `~/.local/state/dlens`, and a benchmark run never
  sees a UI answer in its cache.
- **Budgets.** Gemini and OpenAI-compatible each get a daily call budget in the panel (default
  50), enforced by the same `QuotaCounter` the CLI uses, but counted in the UI's own state file.
- **Redaction.** Every error or refusal shown is passed through `redact`, and the run kept in
  history goes through `scrub_run`. Run logs are written by `RedactingRunLogger`, a subclass of
  the agent's `RunLogger` that lives in the UI package, so agent code stays frozen. This covers
  a provider that echoes the key back. Tests use a sentinel key and check that it never appears
  in the rendered output, the user session state, any file under the project or HOME, or the
  cache and quota sqlite files.
- **What a test cannot remove.** Streamlit keeps a password widget's value in its internal
  widget store for the session (that is how the box keeps its content across reruns). It is in
  memory only and never sent back in an element. The browser tab holds what the user typed.
- **Never use the dlens-eval key in the UI.** The benchmark's Gemini project and its quota plan
  belong to the eval runs only; a UI question would spend from that budget invisibly to the
  eval quota counter (the UI counts in its own file). Use a separate key.

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
- **A separate app for `dlens ui`** (S14). It would drift from the demo and `make ui`, as
  deploy.md argues for demo mode. Instead the mode changes inputs (one project, provider panel,
  tab set) and reuses the same Ask, answer and diagram code.
- **Reading keys from the environment like the CLI does** (S14). The owner's shell holds the
  dlens-eval key, so a convenient UI would spend benchmark quota without anyone noticing.
  Naming the variable explicitly costs one field.
- **Storing the key in `st.session_state`** (S14). Session state is what gets dumped, debugged
  and restored. The unkeyed password widget plus a per-call `Secret` keeps the key out of it.
- **Building the graph from `dlens ui`** (S14). Ingest is the step that prints coverage and
  what failed. Hiding it inside the UI would lose that, and a UI start would sometimes take
  minutes.
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

### Project mode (S14)
4. `provider_env` does not start from `os.environ`. Name two concrete things that would go wrong
   for the benchmark or for privacy if it did.
5. A provider echoes the key in its error message. Trace that string from the provider to each
   place it could surface (error box, history, run log, cache) and name the code that stops it
   at each.
6. Ask in the UI should be "the same system as S4". What exactly is shared (which call, which
   Toolbox construction), and what differs when the retrieval extra or the index is missing?

(Not a core module in CLAUDE.md's sense: no lineage, metrics, scorer or validator code changed.)
