"""DLens local UI: header, then the tabs Ask | Explore lineage | How it works. Layout only; the
agent, validator and renderer are reused unchanged, and every helper in ``dlens.ui.view`` is pure.

    make ui        # uv run streamlit run src/dlens/ui/app.py

Ollama only: the provider is fixed and shown read-only.
"""

from __future__ import annotations

from html import escape

import streamlit as st

import dlens.agent.llm as llm
from dlens.agent.answer import render, warning_line
from dlens.agent.loop import ask as run_agent
from dlens.agent.runlog import RunLogger, runs_dir
from dlens.agent.tools import Toolbox
from dlens.graph import LineageGraph, load_or_build
from dlens.ui import style, view

PROVIDER = "ollama"
EMPTY = "Ask where a column comes from or what it affects. Every claim is checked against the code."


@st.cache_resource(show_spinner="Building the lineage graph (first run takes ~10 s)...")
def load_graph(project: str) -> LineageGraph:
    return load_or_build(view.PROJECTS[project])


# -- state changes (callbacks) ------------------------------------------------------------------


def _ask(project: str, question: str) -> None:
    try:
        client = llm.make_client(PROVIDER)
        box = Toolbox(load_graph(project), view.PROJECTS[project])
        run = run_agent(question, client, box, RunLogger(runs_dir()), project=project)
    except Exception as e:  # the agent already turns provider errors into refusals
        st.session_state.update(error=f"{type(e).__name__}: {e}", run=None)
        return
    hint = view.error_hint(run.answer.refusal_reason) if run.answer.refused else None
    if hint is not None:  # a provider failure is an error state, not a refusal
        st.session_state.update(error=run.answer.refusal_reason, run=None)
        return
    st.session_state.update(error=None, run=run, box=box, project_of_run=project, selected=None)


def _example(text: str) -> None:
    st.session_state.question = text
    st.session_state.pending = True


def _pick(cite_id: str) -> None:
    st.session_state.selected = cite_id
    st.session_state.detail = "Source"


# -- pieces -------------------------------------------------------------------------------------


def show_hint(hint: view.Hint) -> None:
    st.error(f"**{hint.title}**  \n{hint.body}")
    for cmd in hint.commands:
        st.code(cmd, language="bash")


def header() -> str | None:
    """Title, project picker and stats. Returns the project, or None if it cannot be opened."""
    names = list(view.PROJECTS)
    wanted = st.query_params.get("project")
    title, pick, stats, provider = st.columns([1.1, 1.4, 3.2, 1.6], vertical_alignment="bottom")
    title.markdown("## DLens")
    if wanted is not None and wanted not in view.PROJECTS:
        show_hint(view.project_problem(wanted) or view.Hint("Unknown project", ""))
        return None
    project = pick.selectbox(
        "Project",
        names,
        index=names.index(wanted) if wanted else 0,
        key="project",
    )
    provider.markdown(style.muted("Local model (Ollama)"), unsafe_allow_html=True)
    problem = view.project_problem(project)
    if problem is not None:
        show_hint(problem)
        return None
    try:
        graph = load_graph(project)
    except Exception as e:  # dbt or the parser failed: say how to rebuild
        show_hint(view.build_failed(project, e))
        return None
    stats.markdown(
        f'<div class="dl-stats">{escape(view.project_stats(graph).line)}</div>',
        unsafe_allow_html=True,
    )
    return project


def question_panel(project: str) -> None:
    st.text_area(
        "Question",
        key="question",
        height=110,
        placeholder="e.g. Where does fct_orders.revenue come from?",
    )
    asked = st.button(
        "Ask",
        type="primary",
        width="stretch",
        disabled=not st.session_state.get("question", "").strip(),
    )
    if asked or st.session_state.pop("pending", False):
        with st.spinner("Asking the local model..."):
            _ask(project, st.session_state.question.strip())
    groups = view.examples(project)
    if groups:
        st.markdown("**Examples**")
        for g, group in enumerate(groups):
            st.markdown(f"{group.label}  \n{style.muted(group.hint)}", unsafe_allow_html=True)
            for i, q in enumerate(group.questions):
                st.button(
                    q,
                    key=f"ex{g}-{i}",
                    on_click=_example,
                    args=(q,),
                    type="tertiary",
                    width="stretch",
                )


def empty_state(project: str) -> None:
    st.markdown(f"#### {EMPTY}")
    groups = view.examples(project)
    cols = st.columns(2)
    for n, group in enumerate(groups[:4]):
        cols[n % 2].button(
            group.questions[0], key=f"empty{n}", on_click=_example, args=(group.questions[0],)
        )


def answer_panel(project: str) -> None:
    error = st.session_state.get("error")
    if error:
        show_hint(view.error_hint(error) or view.Hint("The question could not be answered", error))
    run = st.session_state.get("run")
    if run is None:
        if not error:
            empty_state(project)
        return
    answer = run.answer
    if (warn := warning_line(answer)) is not None:
        st.warning(warn)
    st.markdown(answer.answer_text.strip())
    if answer.clarification is not None:
        st.markdown("\n".join(f"- {c}" for c in answer.clarification.candidates))
    for n, claim in enumerate(answer.claims):
        st.markdown(f"- {claim.text.strip()}")
        for cid in dict.fromkeys(claim.ids):
            cite = answer.citations.get(cid)
            if cite is not None:
                st.button(
                    view.chip_label(cid, cite), key=f"chip{n}-{cid}", on_click=_pick, args=(cid,)
                )
    details()


def details() -> None:
    lineage, source, steps, checks = st.tabs(
        ["Lineage", "Source", "Steps", "Checks"], key="detail", on_change="rerun"
    )
    answer, box = st.session_state.run.answer, st.session_state.box
    selected = st.session_state.get("selected")
    with lineage:
        if answer.subgraph:
            st.graphviz_chart(view.subgraph_dot(answer, box, selected), width="stretch")
        else:
            st.caption("No edges cited.")
    with source:
        cite = answer.citations.get(selected) if selected else None
        if cite is None:
            st.caption("Select a citation to see the source lines.")
        else:
            src = view.load_source(box.project_dir, cite)
            if src is None:
                st.error(f"{cite.file} could not be read.")
            else:
                st.markdown(f"`{src.file}` · highlighted: **{src.range_label}**")
                st.code(src.text, language="sql", line_numbers=True)
    with steps:
        t = view.trace_info(st.session_state.run)
        st.write(f"{t['llm_calls']} LLM calls · validator: {t['validator']}")
        st.dataframe(view.trace_rows(st.session_state.run), hide_index=True)
    with checks:
        st.code(render(answer), language=None)


def ask_tab(project: str) -> None:
    left, right = st.columns([3, 7], gap="large")
    with left:
        question_panel(project)
    with right:
        answer_panel(project)


def main() -> None:
    st.set_page_config(page_title="DLens", layout="wide")
    st.markdown(style.CSS, unsafe_allow_html=True)
    project = header()
    if project is None:
        return
    ask, explore, how = st.tabs(["Ask", "Explore lineage", "How it works"])
    with ask:
        ask_tab(project)
    with explore:
        st.caption("Coming in this release.")
    with how:
        st.caption("Coming in this release.")


main()
