"""DLens local UI: question | answer | source. Layout only; the agent, validator and renderer are
reused unchanged and the helpers in ``dlens.ui.view`` are pure.

    make ui        # uv run streamlit run src/dlens/ui/app.py

Ollama only: the provider is fixed and shown read-only.
"""

from __future__ import annotations

import streamlit as st

import dlens.agent.llm as llm
from dlens.agent.answer import render, warning_line
from dlens.agent.loop import ask as run_agent
from dlens.agent.runlog import RunLogger, runs_dir
from dlens.agent.tools import Toolbox
from dlens.graph import LineageGraph, load_or_build
from dlens.ui import view

PROVIDER = "ollama"


@st.cache_resource(show_spinner="Building the lineage graph (first run takes ~10 s)...")
def load_graph(project: str) -> LineageGraph:
    return load_or_build(view.PROJECTS[project])


def _ask(project: str, question: str) -> None:
    try:
        client = llm.make_client(PROVIDER)
        box = Toolbox(load_graph(project), view.PROJECTS[project])
        run = run_agent(question, client, box, RunLogger(runs_dir()), project=project)
    except (
        Exception
    ) as e:  # shown to the user; the agent already turns provider errors into refusals
        st.session_state.error = f"{type(e).__name__}: {e}"
        return
    st.session_state.update(error=None, run=run, box=box, project_of_run=project, selected=None)


def _pick(cite_id: str) -> None:
    st.session_state.selected = cite_id


def _set_question(text: str) -> None:
    st.session_state.question = text


def left() -> None:
    st.subheader("Question")
    project = st.selectbox("Project", list(view.PROJECTS), key="project")
    st.text_input("Provider", PROVIDER, disabled=True)
    st.text_area("Ask about a column", key="question", height=100)
    if st.button("Ask", type="primary", disabled=not st.session_state.get("question", "").strip()):
        with st.spinner("Asking the local model..."):
            _ask(project, st.session_state.question.strip())
    presets = view.presets(project)
    if presets:
        st.caption("Presets (passed on the dev set)")
        for i, q in enumerate(presets):
            st.button(
                q, key=f"preset{i}", on_click=_set_question, args=(q,), use_container_width=True
            )


def middle() -> None:
    st.subheader("Answer")
    if st.session_state.get("error"):
        st.error(st.session_state.error)
    run = st.session_state.get("run")
    if run is None:
        st.info("Pick a question and press Ask.")
        return
    answer = run.answer
    if (warn := warning_line(answer)) is not None:
        st.warning(warn)
    st.markdown(answer.answer_text.strip())
    if answer.clarification is not None:
        st.markdown("\n".join(f"- {c}" for c in answer.clarification.candidates))
    st.markdown("**Claims**" if answer.claims else "")
    for n, claim in enumerate(answer.claims):
        st.markdown(f"- {claim.text.strip()}")
        for cid in dict.fromkeys(claim.ids):
            cite = answer.citations.get(cid)
            if cite is not None:
                st.button(
                    view.chip_label(cid, cite), key=f"chip{n}-{cid}", on_click=_pick, args=(cid,)
                )
            elif cid.startswith("r_"):
                st.caption("[graph check]")
    with st.expander("Trace"):
        t = view.trace_info(run)
        st.write(
            f"{t['llm_calls']} LLM calls · {t['tool_calls']} tool calls "
            f"({t['deduped']} deduped, {t['code_calls']} by code) · "
            f"max input ~{t['max_input_tokens_est']:,} tok · "
            f"cached {t['cached_calls']}/{t['llm_calls']} "
            f"· validator: {t['validator']}"
        )
        st.dataframe(view.trace_rows(run), hide_index=True)
        with st.expander("Plain-text answer (as the CLI prints it)"):
            st.code(render(answer), language=None)


def right() -> None:
    st.subheader("Source")
    run = st.session_state.get("run")
    if run is None:
        return
    answer, box = run.answer, st.session_state.box
    selected = st.session_state.get("selected")
    cite = answer.citations.get(selected) if selected else None
    if cite is None:
        st.caption("Click a citation chip to see the source lines.")
    else:
        src = view.load_source(box.project_dir, cite)
        if src is None:
            st.error(f"{cite.file} could not be read.")
        else:
            st.markdown(f"`{src.file}` · highlighted: **{src.range_label}**")
            if src.cited:
                st.code(src.cited, language="sql")
            with st.expander("Whole file", expanded=cite.level == "model"):
                st.code(src.text, language="sql", line_numbers=True)
    st.markdown("**Subgraph of the cited edges**")
    if answer.subgraph:
        st.graphviz_chart(view.subgraph_dot(answer, box, selected), use_container_width=True)
    else:
        st.caption("No edges cited.")


def main() -> None:
    st.set_page_config(page_title="DLens", layout="wide")
    st.title("DLens")
    a, b, c = st.columns([1, 1.5, 1.5], gap="large")
    with a:
        left()
    with b:
        middle()
    with c:
        right()


main()
