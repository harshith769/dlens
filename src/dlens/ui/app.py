"""DLens local UI: header, then the tabs Ask | Explore lineage | How it works. Layout only; the
agent, validator and renderer are reused unchanged, and every helper in ``dlens.ui.view`` is pure.

    make ui        # uv run streamlit run src/dlens/ui/app.py

Locally the provider is Ollama, fixed and shown read-only. In demo mode (``DLENS_DEMO=1``, see
``dlens.ui.demo`` and docs/deploy.md) it is Gemini Flash-Lite behind the demo caps.
"""

from __future__ import annotations

import json
import os
from html import escape

import streamlit as st
from streamlit.delta_generator import DeltaGenerator

import dlens.agent.llm as llm
from dlens.agent.answer import render, warning_line
from dlens.agent.loop import AgentRun
from dlens.agent.loop import ask as run_agent
from dlens.agent.runlog import RunLogger, runs_dir
from dlens.agent.tools import Toolbox
from dlens.graph import LineageGraph, load_or_build
from dlens.ui import demo, style, view

PROVIDER = "ollama"
INTRO = (
    "Ask where a dbt column comes from or what it affects. Every claim is checked against the code."
)
REPO = "https://github.com/harshith769/dlens"
EMPTY = "Pick an example or type a question."
_SLOT: DeltaGenerator | None = None  # the header's provider placeholder, set on every run


@st.cache_resource(show_spinner="Building the lineage graph (first run takes ~10 s)...")
def load_graph(project: str) -> LineageGraph:
    if demo.enabled():  # prebuilt bundle: no dbt, no target/
        return demo.load_graph(view.projects()[project])
    return load_or_build(view.projects()[project])


# -- state changes (callbacks) ------------------------------------------------------------------


def _secrets() -> dict[str, str]:
    """The demo's key and model ID from Streamlit secrets; {} when there is no secrets file.
    Values are never printed or logged."""
    try:
        return {k: str(st.secrets[k]) for k in demo.SECRET_KEYS if k in st.secrets}
    except Exception:  # no secrets.toml (local runs)
        return {}


def _demo_env() -> dict[str, str]:
    return demo.client_env(os.environ, _secrets())


def _limit(limit: demo.Limit) -> None:
    st.session_state.update(limit=limit, error=None, run=None)


def _ask(project: str, question: str) -> None:
    st.session_state.limit = None
    env: dict[str, str] | None = None
    if demo.enabled():
        env = _demo_env()
        asked = st.session_state.get("live_asked", 0)
        blocked = demo.gate(question, asked, demo.calls_left(env), demo.has_key(env))
        if blocked is not None:
            _limit(blocked)
            return
        st.session_state.live_asked = asked + 1
    try:
        client = llm.make_client(demo.PROVIDER, env) if env else llm.make_client(PROVIDER)
        box = Toolbox(load_graph(project), view.projects()[project])
        logs = RunLogger(runs_dir(env))
        run = run_agent(question, client, box, logs, project=project)
    except Exception as e:  # the agent already turns provider errors into refusals
        reason = f"{type(e).__name__}: {e}"
        if env is not None and (failed := demo.failure(reason)) is not None:
            _limit(failed)
        else:
            st.session_state.update(error=reason, run=None)
        return
    if env is not None and run.answer.refused:
        if (failed := demo.failure(run.answer.refusal_reason)) is not None:
            _limit(failed)
            return
    hint = view.error_hint(run.answer.refusal_reason) if run.answer.refused else None
    if hint is not None:  # a provider failure is an error state, not a refusal
        st.session_state.update(error=run.answer.refusal_reason, run=None)
        return
    st.session_state.update(error=None, run=run, box=box, project_of_run=project, selected=None)
    entry = {"question": question, "project": project, "run": run, "box": box}
    st.session_state.history = view.push_history(st.session_state.get("history") or [], entry)


def _restore(n: int) -> None:
    h = st.session_state.history[n]
    st.session_state.update(
        error=None, run=h["run"], box=h["box"], project_of_run=h["project"], selected=None
    )


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


def provider_slot(slot: DeltaGenerator) -> None:
    """The header's provider, and "x of N left today" for a quota-limited provider (None for
    Ollama). Whether an answer was cached is shown on the answer itself."""
    if demo.enabled():
        env = _demo_env()
        quota = (demo.calls_left(env), demo.DAILY_CALLS) if demo.has_key(env) else None
        parts = view.provider_status(demo.PROVIDER, quota)
        if not demo.has_key(env):
            parts.append("live questions off")
    else:
        parts = view.provider_status(PROVIDER, None)
    status = " · ".join(parts)
    slot.markdown(f'<div class="dl-provider">{style.muted(status)}</div>', unsafe_allow_html=True)


def header() -> str | None:
    """Title and intro with the provider on the right, then the project picker and stats. The
    project is None if it cannot be opened."""
    names = list(view.projects())
    wanted = st.query_params.get("project")
    title, provider = st.columns([4, 1.4], vertical_alignment="top")
    title.markdown("## DLens")
    title.markdown(style.intro(INTRO, REPO, "Source on GitHub"), unsafe_allow_html=True)
    global _SLOT
    _SLOT = provider.empty()
    provider_slot(_SLOT)
    if wanted is not None and wanted not in view.projects():
        show_hint(view.project_problem(wanted) or view.Hint("Unknown project", ""))
        return None
    pick, stats = st.columns([1.5, 4], vertical_alignment="bottom")
    project = pick.selectbox(
        "Project",
        names,
        index=names.index(wanted) if wanted else 0,
        key="project",
    )
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
        max_chars=demo.MAX_QUESTION_CHARS if demo.enabled() else None,
    )
    asked = st.button(
        "Ask",
        type="primary",
        width="stretch",
        disabled=not st.session_state.get("question", "").strip(),
    )
    if asked or st.session_state.pop("pending", False):
        model = "Gemini Flash-Lite" if demo.enabled() else "the local model"
        with st.spinner(f"Asking {model}..."):
            _ask(project, st.session_state.question.strip())
        if demo.enabled() and _SLOT is not None:
            provider_slot(_SLOT)  # the header rendered before this call spent quota
    history = st.session_state.get("history") or []
    if history:
        st.markdown("**This session**")
        with st.container(key="history", gap=None):
            for n, h in enumerate(history):
                v = view.verdict(h["run"])
                st.button(
                    view.history_label(h["question"], v.tone),
                    key=f"hist{n}",
                    help=f"{h['question']} ({v.label})",
                    on_click=_restore,
                    args=(n,),
                    type="tertiary",
                    width="stretch",
                )
    groups = view.examples(project)
    if groups:
        st.markdown("**Examples**")
        for g, group in enumerate(groups):
            st.markdown(
                f'<div class="dl-group" title="{escape(group.hint)}">{escape(group.label)}</div>',
                unsafe_allow_html=True,
            )
            with st.container(key=f"examples{g}", gap="small"):
                for i, q in enumerate(group.questions):
                    st.button(q, key=f"ex{g}-{i}", on_click=_example, args=(q,), width="stretch")


def empty_state(project: str) -> None:
    st.markdown(f"#### {EMPTY}")
    groups = view.examples(project)
    with st.container(key="empty", horizontal=True, gap="small"):
        for n, group in enumerate(groups[:4]):
            q = group.questions[0]
            st.button(q, key=f"empty{n}", on_click=_example, args=(q,))


def answer_panel(project: str) -> None:
    limit = st.session_state.get("limit")
    if limit:
        title, body = limit
        st.warning(f"**{title}**  \n{body}")
    error = st.session_state.get("error")
    if error:
        show_hint(view.error_hint(error) or view.Hint("The question could not be answered", error))
    run = st.session_state.get("run")
    if run is None:
        if not error and not limit:
            empty_state(project)
        return
    answer = run.answer
    badges = [view.verdict(run), view.verification(run)]
    if view.run_cached(run):
        badges.append(view.CACHED)
    html = "".join(style.badge(b.label, b.tone, b.help) for b in badges)
    st.markdown(html, unsafe_allow_html=True)
    asked_on = st.session_state.get("project_of_run")
    if asked_on and asked_on != project:
        st.caption(f"Asked on {asked_on}.")
    if (warn := warning_line(answer)) is not None:
        st.warning(warn)
    st.markdown(answer.answer_text.strip())
    if answer.clarification is not None:
        st.markdown("\n".join(f"- {c}" for c in answer.clarification.candidates))
    claims(run)
    details()
    exports(run)


def claims(run: AgentRun) -> None:
    rows = view.claim_rows(run)
    if rows:
        st.markdown("**Claims**")
    for n, row in enumerate(rows):
        st.markdown(style.claim_line(row.text, row.status), unsafe_allow_html=True)
        with st.container(horizontal=True, gap="small", key=f"chips{n}"):
            for cid, label in row.chips:
                st.button(label, key=f"chip{n}-{cid}", on_click=_pick, args=(cid,))
    removed = view.removed_claims(run)
    if removed:
        with st.expander(f"Removed by the validator ({len(removed)})"):
            for r in removed:
                rules = ", ".join(r.rules) or "?"
                st.markdown(f"- {r.text or '(text not recorded)'} · failed {rules}")


def exports(run: AgentRun) -> None:
    project = st.session_state.get("project_of_run", "")
    data = view.answer_export(run, project, view.run_facts(run, st.session_state.box))
    stem = f"dlens-answer-{run.record.run_id[:8]}"
    with st.container(horizontal=True, gap="small", key="exports"):
        st.download_button(
            "Download Markdown",
            view.answer_markdown(data),
            file_name=f"{stem}.md",
            mime="text/markdown",
            on_click="ignore",
        )
        st.download_button(
            "Download JSON",
            json.dumps(data, indent=2, ensure_ascii=False),
            file_name=f"{stem}.json",
            mime="application/json",
            on_click="ignore",
        )


def details() -> None:
    lineage, source, steps, checks = st.tabs(
        ["Lineage", "Source", "Steps", "Checks"], key="detail", on_change="rerun"
    )
    answer, box = st.session_state.run.answer, st.session_state.box
    selected = st.session_state.get("selected")
    with lineage:
        lineage_view(st.session_state.run, box, selected)
    with source:
        source_view(st.session_state.run, box, selected)
    with steps:
        run = st.session_state.run
        t = view.trace_info(run)
        st.caption(
            f"{t['llm_calls']} LLM calls · {t['tool_calls']} tool calls "
            f"({t['deduped']} duplicates skipped, {t['code_calls']} by code) · "
            f"cached {t['cached_calls']}/{t['llm_calls']}"
        )
        items = [(i.title, i.detail, i.meta, i.kind) for i in view.timeline(run)]
        st.markdown(style.timeline(items), unsafe_allow_html=True)
    with checks:
        rows = view.checks_table(st.session_state.run)
        st.dataframe(
            [
                {
                    "Rule": r.rule,
                    "What it checks": r.meaning,
                    "Outcome": r.outcome,
                    "Failures": r.failures,
                }
                for r in rows
            ],
            hide_index=True,
            column_config={"What it checks": st.column_config.TextColumn(width="large")},
        )
        with st.expander("Plain-text answer (as the CLI prints it)"):
            st.code(render(answer), language=None)


def diagram(d: view.LineageDot) -> None:
    if d.shown == 0:
        st.caption("No edges to draw.")
        return
    if d.kinds:
        st.markdown(style.legend_row(d.kinds), unsafe_allow_html=True)
    st.graphviz_chart(d.dot, width=d.width)
    if d.note:
        st.caption(d.note)


def lineage_view(run: AgentRun, box: Toolbox, selected: str | None) -> None:
    graph = box.graph
    focus, direction = view.focus_column(run, graph)
    modes = ["Cited edges", "Full lineage of the column"]
    mode = st.segmented_control(
        "Show",
        modes,
        default=modes[0],
        key="lineage_mode",
        label_visibility="collapsed",
        disabled=focus is None,
    )
    if mode == modes[1] and focus is not None:
        edges = view.neighborhood(graph, focus, direction, depth=10)
        st.caption(f"{direction.capitalize()} of {graph.display_name(focus)}")
    else:
        edges = view.edges_by_id(graph, run.answer.subgraph)
    highlight = frozenset([selected]) if selected else frozenset()
    diagram(view.build_lineage_dot(graph, edges, focus, highlight))


def source_view(run: AgentRun, box: Toolbox, selected: str | None) -> None:
    chips = [c for row in view.claim_rows(run) for c in row.chips]
    if selected is None and chips:
        selected = chips[0][0]  # show the first citation until one is picked
    if selected is None:
        st.caption("This answer cites no file.")
        return
    if selected.startswith("r_"):
        fact = view.fact_statement(box, selected) or "(fact not found)"
        st.markdown("**Graph check**")
        st.markdown(
            style.muted("Checked on the lineage graph by code, not in a file."),
            unsafe_allow_html=True,
        )
        st.info(fact)
        return
    cite = run.answer.citations.get(selected)
    src = view.load_source(box.project_dir, cite) if cite is not None else None
    if cite is None or src is None:
        st.error(f"{cite.file if cite else selected} could not be read inside the project.")
        return
    st.markdown(f"`{src.file}` · level: {src.level} · highlighted: **{src.range_label}**")
    st.html(view.highlight_sql(src.text, src.highlighted, sql=src.file.endswith(".sql")))


def ask_tab(project: str) -> None:
    left, right = st.columns([3, 7], gap="large")
    with left:
        question_panel(project)
    with right:
        answer_panel(project)


def explore_tab(project: str) -> None:
    """Lineage straight from the graph: no LLM call, no quota."""
    graph = load_graph(project)
    options = view.column_options(graph)
    if not options:
        st.caption("This project has no columns.")
        return
    pick, way, depth_col = st.columns([3, 2, 2], vertical_alignment="bottom")
    name = pick.selectbox("Column", list(options), key="explore_col")
    direction = way.segmented_control(
        "Direction", list(view.DIRECTIONS), default="Upstream", key="explore_dir"
    )
    depth = depth_col.slider("Depth", 1, 10, 3, key="explore_depth")
    focus = options[name]
    edges = view.neighborhood(graph, focus, view.DIRECTIONS[direction or "Upstream"], depth)
    d = view.build_lineage_dot(graph, edges, focus)
    if d.shown == 0:
        st.caption(f"{name} has no {(direction or 'upstream').lower()} lineage.")
    else:
        diagram(d)
    shown = edges[: d.shown]
    if shown:
        st.markdown("**Edges**")
        st.dataframe(view.explore_rows(graph, view.projects()[project], shown), hide_index=True)
    models = view.edge_models(graph, shown, focus)
    uid = st.selectbox(
        "Model SQL",
        models,
        format_func=lambda u: (graph.model_info(u) or {}).get("name", u),
        key="explore_model",
    )
    if uid is None:
        return
    src = view.model_source(graph, view.projects()[project], uid)
    if src is None:
        st.caption("No source file inside the project for this model.")
        return
    st.markdown(f"`{src.file}`")
    st.html(view.highlight_sql(src.text, sql=src.file.endswith(".sql")))


def how_tab() -> None:
    st.markdown("#### From question to cited answer")
    st.markdown(style.pipeline(view.PIPELINE), unsafe_allow_html=True)
    st.caption(view.PIPELINE_NOTE)
    st.markdown(
        "The model only narrates what the tools returned. Code attaches every file and line, "
        "and the validator checks each claim before you see it."
    )
    rules, score = st.columns([3, 2], gap="large")
    with rules:
        st.markdown("#### The nine rules")
        st.markdown("\n".join(f"- **{r}** {m}" for r, m in view.NINE_RULES))
        st.caption(
            "Two code steps help before the rules run: R2r fixes a miscopied id, "
            "R8c adds a missing connecting edge the tools returned."
        )
    with score:
        s = view.dev_score()
        st.markdown("#### Current score")
        if s is None:
            st.caption("No dev report yet: run make eval-smoke.")
            return
        st.metric(s.label, f"{s.passed} of {s.questions} pass")
        st.caption(
            f"Verdict right on {s.verdict_ok} of {s.questions} · mean edge recall "
            f"{s.mean_recall:.2f} · report of {s.date} (eval/reports/dev_r9.json)"
        )


def main() -> None:
    st.set_page_config(page_title="DLens", layout="wide")
    st.html(style.CSS + f"<style>{view.source_css()}</style>")
    project = header()
    if project is None:
        return
    ask, explore, how = st.tabs(["Ask", "Explore lineage", "How it works"])
    with ask:
        ask_tab(project)
    with explore:
        explore_tab(project)
    with how:
        how_tab()


main()
