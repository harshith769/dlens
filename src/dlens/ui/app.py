"""DLens local UI: header, then the tabs Ask | Explore lineage | How it works. Layout only; the
agent, validator and renderer are reused unchanged, and every helper in ``dlens.ui.view`` is pure.

    make ui        # uv run streamlit run src/dlens/ui/app.py

Locally the provider is Ollama, fixed and shown read-only. In demo mode (``DLENS_DEMO=1``, see
``dlens.ui.demo`` and docs/deploy.md) it is Gemini Flash-Lite behind the demo caps. In project
mode (``dlens ui --project DIR``, see ``dlens.ui.project``) the app opens one ingested project
with the tabs Explore | Trace / Impact | Source | Ask | How it works, and Ask uses the provider
the user picks (Ollama by default).
"""

from __future__ import annotations

import json
import os
from html import escape
from pathlib import Path
from typing import TYPE_CHECKING

import streamlit as st
from streamlit.delta_generator import DeltaGenerator

import dlens.agent.llm as llm
from dlens.agent.answer import render, warning_line
from dlens.agent.llm.ollama import DEFAULT_MODEL as OLLAMA_MODEL
from dlens.agent.loop import AgentRun
from dlens.agent.loop import ask as run_agent
from dlens.agent.runlog import RunLogger, runs_dir
from dlens.agent.tools import Toolbox
from dlens.graph import LineageGraph, load_or_build
from dlens.graph.render import render_impact, render_trace
from dlens.graph.report import coverage_summary
from dlens.ui import demo, style, view
from dlens.ui import project as local

if TYPE_CHECKING:
    from dlens.retrieval.index import SearchIndex

PROVIDER = "ollama"
KEY_NOTE = "Your key stays in this browser session's memory only; it is never saved."
# Project mode: a path or command in a caption or hint never breaks across lines.
PROJECT_CSS = (
    "<style>[data-testid='stCaptionContainer'] code, .stAlert code { white-space: nowrap; }"
    ".dl-path { font-size: 0.8rem; opacity: 0.75; }</style>"
)
LOC = local.from_env(os.environ)  # project mode (``dlens ui --project``) when set
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
    if LOC is not None:  # the graph `dlens ingest --artifacts` wrote; never built here
        return local.load(LOC)
    return load_or_build(view.projects()[project])


@st.cache_resource(show_spinner="Opening the search index...")
def load_index(project: str) -> tuple[SearchIndex | None, str]:
    assert LOC is not None
    return local.open_index(LOC, load_graph(project))


@st.cache_resource(show_spinner=False)
def load_presets(directory: str) -> dict[str, demo.Preset]:
    return {p.id: p for p in demo.load_presets(Path(directory))}


def presets() -> list[demo.Preset]:
    return list(load_presets(str(demo.presets_dir())).values()) if demo.enabled() else []


PRESET_HELP = "Recorded earlier with the local model and replayed here: no model call, no quota."


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
    _store(project, question, run, box)


def _store(project: str, question: str, run: AgentRun, box: Toolbox) -> None:
    st.session_state.update(
        error=None,
        ask_hint=None,
        run=run,
        box=box,
        project_of_run=project,
        selected=None,
        preset=None,
    )
    entry = {"question": question, "project": project, "run": run, "box": box}
    st.session_state.history = view.push_history(st.session_state.get("history") or [], entry)


def _fail(hint: view.Hint) -> None:
    st.session_state.update(error=None, run=None, ask_hint=hint)


def _ask_local(
    project: str, question: str, choice: local.ProviderChoice, secret: local.Secret | None
) -> None:
    """Project mode: the same agent loop and validator as S4, on the provider the user picked.
    The key exists only in ``secret`` and the per-ask env; every text shown or logged is
    redacted, and the cache, quota and run logs live under ``<target>/dlens/ui/``."""
    assert LOC is not None
    st.session_state.update(limit=None, ask_hint=None)
    if (problem := local.ask_problem(choice, secret)) is not None:
        _fail(problem)
        return
    secrets = [secret]
    try:
        client = llm.make_client(choice.kind, local.provider_env(choice, secret, LOC))
        index, _ = load_index(project)
        box = Toolbox(load_graph(project), LOC.project_dir, index)
        logs = local.RedactingRunLogger(LOC.ui_dir / "runs", secrets)
        run = local.scrub_run(run_agent(question, client, box, logs, project=project), secrets)
    except Exception as e:  # the agent already turns provider errors into refusals
        failed = local.redact(f"{type(e).__name__}: {e}", secrets)
        _fail(view.Hint("The question could not be answered", failed))
        return
    reason = run.answer.refusal_reason if run.answer.refused else None
    if reason and choice.kind == "ollama" and (hint := view.error_hint(reason)) is not None:
        _fail(hint)
        return
    if reason and reason.lower().startswith("providererror"):
        _fail(view.Hint(f"The {choice.label} call failed", reason))
        return
    _store(project, question, run, box)


def _restore(n: int) -> None:
    h = st.session_state.history[n]
    st.session_state.update(
        error=None,
        limit=None,
        ask_hint=None,
        run=h["run"],
        box=h["box"],
        project_of_run=h["project"],
        selected=None,
        preset=h.get("preset"),
    )


def _preset(project: str, pid: str) -> None:
    """Replay a precomputed answer: the tool calls re-run on the graph, no LLM call."""
    p = load_presets(str(demo.presets_dir()))[pid]
    run, box = demo.replay(p, load_graph(project), view.projects()[project])
    st.session_state.update(
        error=None,
        limit=None,
        run=run,
        box=box,
        project_of_run=project,
        selected=None,
        preset=p.badge,
        question=p.question,
    )
    entry = {"question": p.question, "project": project, "run": run, "box": box}
    entry["preset"] = p.badge
    st.session_state.history = view.push_history(st.session_state.get("history") or [], entry)


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
    elif LOC is not None:
        kind = st.session_state.get("ui_provider", "ollama")
        parts = [local.KINDS.get(kind, kind)]
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


def project_header() -> str | None:
    """Project mode: title, the privacy line (shown even when the project cannot be opened),
    then the project and its stats. None if it is not ingested; the hint says what to run."""
    assert LOC is not None
    title, provider = st.columns([4, 1.4], vertical_alignment="top")
    title.markdown("## DLens")
    title.markdown(style.intro(INTRO, REPO, "Source on GitHub"), unsafe_allow_html=True)
    global _SLOT
    _SLOT = provider.empty()
    provider_slot(_SLOT)
    st.caption(local.PRIVACY)
    try:
        graph = load_graph(LOC.name)
    except local.ProjectProblem as e:
        show_hint(e.hint)
        return None
    except Exception as e:  # an unreadable graph: re-ingest
        show_hint(
            view.Hint(
                f"Could not open the lineage graph of {LOC.name}",
                f"{type(e).__name__}: {e}",
                (f"dlens ingest --artifacts {LOC.target} --rebuild",),
            )
        )
        return None
    stats = view.project_stats(graph).line
    st.markdown(
        f'<div class="dl-stats"><b>{escape(LOC.name)}</b> · {escape(stats)}<br>'
        f'<span class="dl-path">{escape(LOC.folder)}</span></div>',
        unsafe_allow_html=True,
    )
    return LOC.name


def provider_panel(project: str) -> tuple[local.ProviderChoice, local.Secret | None]:
    """Project mode: which model answers. A key comes from the password box (unkeyed, so it is
    not in ``st.session_state``) or from an env var the user names; never an ambient key."""
    kind = st.radio(
        "Model",
        list(local.KINDS),
        format_func=lambda k: local.KINDS[k],
        key="ui_provider",
    )
    if kind == "ollama":
        model = st.text_input("Ollama model", value=OLLAMA_MODEL, key="ui_ollama_model")
        choice, secret = local.ProviderChoice("ollama", model.strip()), None
    else:
        base = ""
        if kind == "gemini":
            model = st.text_input("Model ID", value=local.GEMINI_MODEL, key="ui_gemini_model")
        else:
            base = st.text_input(
                "Base URL", key="ui_openai_url", placeholder="https://api.example.com/v1"
            )
            model = st.text_input("Model ID", key="ui_openai_model")
        budget = st.number_input(
            "Daily call budget", 1, 10_000, local.DAILY_BUDGET, key=f"ui_{kind}_budget"
        )
        typed = st.text_input(
            f"{'Gemini' if kind == 'gemini' else 'API'} key (memory only, this session)",
            type="password",
            help="Never written to disk, logged, or shown back.",
        )
        st.caption(KEY_NOTE)
        key_env = st.text_input(
            "Or the name of an environment variable that holds it",
            key=f"ui_{kind}_key_env",
            placeholder="MY_API_KEY",
        )
        choice = local.ProviderChoice(kind, model.strip(), base.strip(), int(budget), key_env)
        secret = local.resolve_key(choice, typed, os.environ)
        if key_env.strip() and not typed.strip():
            st.caption(
                f"Using the key in ${key_env.strip()}."
                if secret
                else f"${key_env.strip()} is not set."
            )
        if choice.cloud:
            st.caption(
                "A cloud provider: your question and the code excerpts the tools return are "
                f"sent to it, at most {int(budget)} model calls a day."
            )
    st.caption(load_index(project)[1])
    return choice, secret


def project_examples(project: str) -> None:
    qs = local.example_questions(load_graph(project))
    if not qs:
        return
    st.markdown("**Examples**")
    with st.container(key="pexamples", gap="small"):
        for i, q in enumerate(qs):
            st.button(q, key=f"pex{i}", on_click=_example, args=(q,), width="stretch")


def question_panel(project: str) -> None:
    picked = provider_panel(project) if LOC is not None else None
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
        if picked is not None and picked[0].kind != "ollama":
            model = picked[0].label.replace(" (your key)", "")
        with st.spinner(f"Asking {model}..."):
            if picked is not None:
                _ask_local(project, st.session_state.question.strip(), *picked)
            else:
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
    if demo.enabled():
        preset_list(project)
        return
    if LOC is not None:
        project_examples(project)
        return
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


def preset_list(project: str) -> None:
    items = presets()
    if not items:
        return
    st.markdown("**Presets**")
    st.caption(f"{items[0].badge} · instant, no quota")
    with st.container(key="presets", gap="small"):
        for p in items:
            st.button(
                view.preset_label(p.tag, p.question),
                key=f"preset-{p.id}",
                help=PRESET_HELP,
                on_click=_preset,
                args=(project, p.id),
                width="stretch",
            )


def empty_state(project: str) -> None:
    if demo.enabled():
        st.markdown("#### Pick a preset or type a question.")
        with st.container(key="empty", horizontal=True, gap="small"):
            for p in presets()[:4]:
                st.button(
                    view.preset_label(p.tag, p.question),
                    key=f"empty-{p.id}",
                    on_click=_preset,
                    args=(project, p.id),
                )
        return
    st.markdown(f"#### {EMPTY}")
    if LOC is not None:
        with st.container(key="empty", horizontal=True, gap="small"):
            for n, q in enumerate(local.example_questions(load_graph(project), n=1)):
                st.button(q, key=f"empty{n}", on_click=_example, args=(q,))
        return
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
    ask_hint = st.session_state.get("ask_hint")  # project mode: already redacted
    if ask_hint:
        show_hint(ask_hint)
    run = st.session_state.get("run")
    if run is None:
        if not error and not limit and not ask_hint:
            empty_state(project)
        return
    answer = run.answer
    badges = [view.verdict(run), view.verification(run)]
    preset = st.session_state.get("preset")
    if preset:
        badges.append(view.Badge(preset, "neutral", PRESET_HELP))
    elif view.run_cached(run):
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
    src = view.load_source(box.project_dir, cite, box.graph) if cite is not None else None
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


def overview_tab(project: str) -> None:
    """Project mode Explore: what DLens sees in the project, and how well it parsed. No LLM."""
    assert LOC is not None
    graph = load_graph(project)
    cov = coverage_summary(graph)
    cells = st.columns(5)
    cells[0].metric("Models parsed", sum(cov.counts.values()))
    for cell, level in zip(cells[1:], ("FULL", "PARTIAL", "TABLE_ONLY", "FAILED"), strict=True):
        cell.metric(level, cov.counts.get(level, 0))
    st.caption(
        f"{local.full_share(cov):.0%} of models FULL (column lineage with no gaps). "
        f"`dlens report --artifacts {LOC.target}` (in the project folder) lists every gap."
    )
    st.markdown("**Models**")
    st.dataframe(local.model_rows(graph, cov), hide_index=True)
    uids = sorted(graph.model_ids(), key=lambda u: (graph.model_info(u) or {}).get("name", u))
    if not uids:
        return
    uid = st.selectbox(
        "Columns of",
        uids,
        format_func=lambda u: (graph.model_info(u) or {}).get("name", u),
        key="ov_model",
    )
    rows = local.column_rows(graph, uid)
    if rows:
        st.dataframe(rows, hide_index=True)
    else:
        st.caption("No columns recorded for this model.")


TRACE_MODES = {"Trace (upstream)": "upstream", "Impact (downstream)": "downstream"}


def trace_tab(project: str) -> None:
    """Project mode Trace / Impact: a column's lineage from the graph, as the CLI computes it."""
    assert LOC is not None
    graph = load_graph(project)
    options = view.column_options(graph)
    if not options:
        st.caption("This project has no columns.")
        return
    pick, way, depth_col = st.columns([3, 2.4, 2], vertical_alignment="bottom")
    name = pick.selectbox(
        "Column", list(options), index=local.default_column(graph, options), key="trace_col"
    )
    mode = way.segmented_control(
        "Direction", list(TRACE_MODES), default="Trace (upstream)", key="trace_dir"
    )
    depth = depth_col.slider("Depth", 1, 10, 3, key="trace_depth")
    indirect = st.toggle(
        "Include indirect edges (join / filter / group / sort / window keys) in the paths",
        key="trace_indirect",
    )
    col, direction = options[name], TRACE_MODES[mode or "Trace (upstream)"]
    edges = view.neighborhood(graph, col, direction, depth)
    d = view.build_lineage_dot(graph, edges, col)
    if d.shown == 0:
        st.caption(f"{name} has no {direction} lineage.")
    else:
        diagram(d)
        st.markdown("**Edges**")
        st.dataframe(view.explore_rows(graph, LOC.project_dir, edges[: d.shown]), hide_index=True)
    if direction == "upstream":
        paths = graph.upstream(col, max_depth=depth, include_indirect=indirect)
        text, cmd = render_trace(graph, col, paths, depth), "trace"
    else:
        result = graph.downstream(col, max_depth=depth, include_indirect=indirect)
        text, cmd = render_impact(graph, result, depth), "impact"
    st.markdown("**Paths**" if cmd == "trace" else "**Impact**")
    st.code(text, language=None)
    flag = " --include-indirect" if indirect else ""
    st.caption(
        f"Same as `dlens {cmd} {name} --artifacts {LOC.target} --depth {depth}{flag}` "
        "in the project folder."
    )


SOURCE_KINDS = ("As written", "Compiled")


def source_tab(project: str) -> None:
    """Project mode Source: read-only, and only the files the graph names inside the project."""
    assert LOC is not None
    graph = load_graph(project)
    files = local.source_files(graph)
    if not files:
        st.caption("The graph names no files.")
        return
    pick, which = st.columns([4, 2], vertical_alignment="bottom")
    file = pick.selectbox("File", files, key="src_file")
    compiled = local.compiled_file(graph, file)
    kind = which.segmented_control(
        "Show", SOURCE_KINDS, default=SOURCE_KINDS[0], key="src_kind", disabled=compiled is None
    )
    if kind == "Compiled" and compiled is not None:
        text, shown = local.read_compiled(LOC, graph, file), f"{LOC.target}/{compiled}"
    else:
        text, shown = local.read_source(LOC, graph, file), file
    if text is None:
        st.error(f"{shown} could not be read inside the project.")
        return
    st.markdown(f"`{shown}` · read-only")
    st.html(view.highlight_sql(text, sql=shown.endswith(".sql")))
    st.caption("Only files the lineage graph names, read from inside the project folder.")


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
        if LOC is not None:  # the dev score is about the corpora, not this project
            st.markdown("#### On this project")
            st.markdown(
                "Explore, Trace / Impact and Source read the lineage graph only: no model call. "
                "Ask sends your question, plus the excerpts the tools return, to the model "
                "you pick under Ask."
            )
            return
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
    st.html(
        style.CSS
        + f"<style>{view.source_css()}</style>"
        + (style.DEMO_CSS if demo.enabled() else "")
        + (PROJECT_CSS if LOC is not None else "")
    )
    if LOC is not None:
        project_main()
        return
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


PROJECT_TABS = ["Explore", "Trace / Impact", "Source", "Ask", "How it works"]


def project_main() -> None:
    project = project_header()
    if project is None:
        return
    explore, trace, source, ask, how = st.tabs(PROJECT_TABS)
    with explore:
        overview_tab(project)
    with trace:
        trace_tab(project)
    with source:
        source_tab(project)
    with ask:
        ask_tab(project)
    with how:
        how_tab()


main()
