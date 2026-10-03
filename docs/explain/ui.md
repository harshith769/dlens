# Explain: local UI (`src/dlens/ui/`)

## What it does
`make ui` starts a three-pane Streamlit app on the local Ollama model (provider is fixed and shown
read-only; no Gemini).

| Pane | Shows |
|---|---|
| Left | project picker (synthetic_shop, jaffle_shop), question box, up to 6 preset questions from `eval/questions/dev.jsonl` that passed in `eval/reports/dev_r9.json` |
| Middle | the answer, the ⚠ banner when `validation_warning` is set, claims with clickable citation chips `[file:lines]`, and a Trace expander (LLM/tool calls, tokens, cached, validator outcome incl. repaired / completed / regenerated) |
| Right | the SOURCE `.sql` for the selected chip (cited lines shown with their real line numbers, whole file below with line numbers), then a Graphviz graph of the cited edges with the edge kind as label |

## How it works
`app.py` is layout only. It calls `Agent`/`ask`, `Toolbox`, `warning_line` and `trace_summary`
unchanged. `view.py` holds pure helpers (presets, chips, source slice, DOT string, trace rows) and
has no Streamlit import. The graph is built once per project with `st.cache_resource`; the last run
and toolbox live in `st.session_state`, so clicking a chip only re-renders. The graph is drawn by
`st.graphviz_chart` from a DOT string (rendered in the browser; no system Graphviz).

## Why this design
No business logic in the UI, so a wrong answer can only be a loop/validator bug, never a UI bug.
`st.code` has no line-highlight option, so the cited range is shown as its own block with true line
numbers, above the numbered whole file.

## Alternatives rejected
Gradio (no clickable per-claim chips as easily); a custom JS front end (out of scope); highlighting
by injecting HTML (needs `unsafe_allow_html` on file content).

## Explain-back questions
1. Why does `view.py` avoid importing Streamlit, and what does that buy the tests?
2. Why are `r_` facts shown as "[graph check]" rather than as chips?
3. What would break if the toolbox were created inside `st.cache_resource` and shared by sessions?

(Not a core module in CLAUDE.md's sense: no lineage, metrics, scorer or validator code changed.)
