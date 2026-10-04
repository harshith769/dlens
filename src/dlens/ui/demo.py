"""Public demo mode (``DLENS_DEMO=1``): the app reads a prebuilt bundle instead of a dbt project.

The bundle (``demo/synthetic_shop/``) holds the saved lineage graph and only the project files the
graph points at: the source ``.sql`` and seed files that the Source tab, ``get_model_sql`` and
validator R3 read. No dbt run, no ``target/``. Build it with ``scripts/build_demo_bundle.py``.

Live questions go to Gemini Flash-Lite on a separate AI Studio project, behind three caps: 50 LLM
calls a day for the whole app (the usual ``QuotaCounter``, in a demo-only state dir), 5 live
questions per browser session, 300 characters per question. A question starts only if a full
agent run (``MAX_LLM_CALLS``) still fits in today's budget, so no answer is cut off half-way.
No Streamlit import here, so it is unit-tested directly.
"""

from __future__ import annotations

import json
import os
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

from dlens.agent.answer import Answer
from dlens.agent.llm.config import quota_path
from dlens.agent.llm.quota import QuotaCounter
from dlens.agent.loop import MAX_LLM_CALLS, AgentRun
from dlens.agent.runlog import RunRecord
from dlens.agent.tools import Toolbox
from dlens.graph import LineageGraph

ROOT = Path(__file__).resolve().parents[3]
PROJECT = "synthetic_shop"
GRAPH_FILE = "graph.json"  # not under target/: that folder is gitignored


def enabled(env: Mapping[str, str] | None = None) -> bool:
    env = os.environ if env is None else env
    return env.get("DLENS_DEMO") == "1"


def bundle_dir(env: Mapping[str, str] | None = None) -> Path:
    """``$DLENS_DEMO_DIR`` if set (tests use a temp copy), else ``demo/`` in the repo."""
    env = os.environ if env is None else env
    return Path(env["DLENS_DEMO_DIR"]) if env.get("DLENS_DEMO_DIR") else ROOT / "demo"


def projects(env: Mapping[str, str] | None = None) -> dict[str, Path]:
    return {PROJECT: bundle_dir(env) / PROJECT}


def load_graph(project_dir: Path) -> LineageGraph:
    return LineageGraph.load(project_dir / GRAPH_FILE)


def bundle_files(graph: LineageGraph) -> list[str]:
    """Every project-relative file the graph cites: model/seed files and edge files."""
    files = {(graph.model_info(m) or {}).get("file", "") for m in graph.model_ids()}
    files |= {e.file for e in graph.edges()}
    return sorted(f for f in files if f)


# -- live questions --------------------------------------------------------------------------------

PROVIDER = "gemini"
DAILY_CALLS = 50
SESSION_QUESTIONS = 5
MAX_QUESTION_CHARS = 300
CALLS_PER_QUESTION = MAX_LLM_CALLS
SECRET_KEYS = ("GEMINI_API_KEY", "DLENS_GEMINI_MODEL")


def state_dir(env: Mapping[str, str] | None = None) -> Path:
    """Demo-only quota, cache and run logs: never the dev counter (``$DLENS_DEMO_STATE_DIR``)."""
    env = os.environ if env is None else env
    if env.get("DLENS_DEMO_STATE_DIR"):
        return Path(env["DLENS_DEMO_STATE_DIR"]).expanduser()
    return Path.home() / ".local" / "state" / "dlens-demo"


def client_env(base: Mapping[str, str], secrets: Mapping[str, str]) -> dict[str, str]:
    """The environment ``make_client`` gets in demo mode: secrets (key, model ID) over ``base``,
    the demo budget and the demo-only state, cache and run dirs."""
    env = dict(base)
    env.update({k: str(secrets[k]) for k in SECRET_KEYS if secrets.get(k)})
    state = state_dir(env)
    env["GEMINI_DAILY_BUDGET"] = str(DAILY_CALLS)
    env["DLENS_STATE_DIR"] = str(state)
    env["DLENS_CACHE_DIR"] = str(state / "cache")
    env["DLENS_RUN_DIR"] = str(state / "runs")
    return env


def has_key(env: Mapping[str, str]) -> bool:
    return bool(env.get("GEMINI_API_KEY"))


def calls_left(env: Mapping[str, str]) -> int:
    """Model calls left today for the whole app (no key needed; reads the counter only)."""
    left = QuotaCounter(quota_path(env), {PROVIDER: DAILY_CALLS}).remaining(PROVIDER)
    return DAILY_CALLS if left is None else left


Limit = tuple[str, str]  # (title, body) of the friendly limit state


def gate(question: str, asked: int, left: int, key: bool = True) -> Limit | None:
    """Why a live question cannot be sent now, or None. ``asked``: live questions this session."""
    preset = "Try a preset question: those replay instantly and make no model call."
    if not key:
        return ("Live questions are off", f"No API key is configured for this demo. {preset}")
    if len(question) > MAX_QUESTION_CHARS:
        return (
            "Question too long",
            f"The demo takes up to {MAX_QUESTION_CHARS} characters ({len(question)} given).",
        )
    if asked >= SESSION_QUESTIONS:
        return (
            "Demo limit reached",
            f"You have asked {SESSION_QUESTIONS} live questions in this session. {preset}",
        )
    if left < CALLS_PER_QUESTION:
        return (
            "Demo limit reached",
            f"Today's {DAILY_CALLS} model calls, shared by every visitor, are used up "
            f"(a question needs up to {CALLS_PER_QUESTION}). {preset} "
            "The budget resets at midnight US Pacific.",
        )
    return None


def failure(reason: str | None) -> Limit | None:
    """A friendly state for a live run that failed at the provider, else None."""
    if not reason:
        return None
    if reason.startswith("QuotaExceeded"):
        return gate("", 0, 0)
    if reason.startswith(("ProviderError", "GeminiConfigError")):
        return (
            "The demo model is unavailable right now",
            "Gemini did not answer (busy or rate-limited). Try again in a minute, or try a "
            "preset question.",
        )
    return None


# -- presets ---------------------------------------------------------------------------------------

# Dev questions that passed in eval/reports/dev_r9.json, one or more per kind: upstream (1 hop and
# multi-hop), abbreviation, downstream impact, a yes/no reachability check (answer "No"),
# computed, ambiguity, false premise and an unknown-column refusal.
PRESET_IDS = (
    "dev-01",
    "dev-05",
    "dev-06",
    "dev-14",
    "dev-07",
    "dev-10",
    "dev-13",
    "dev-16",
    "dev-17",
    "dev-19",
)


@dataclass(frozen=True)
class Preset:
    """A full run recorded with the local model (scripts/record_presets.py), replayed with no
    model call."""

    id: str
    subtype: str
    question: str
    record: RunRecord

    @property
    def badge(self) -> str:
        return f"Precomputed with local {self.record.model.split('-')[0]}"


def presets_dir(env: Mapping[str, str] | None = None) -> Path:
    return bundle_dir(env) / "presets"


def preset_json(qid: str, subtype: str, record: RunRecord) -> str:
    body = {"id": qid, "subtype": subtype, "record": record.model_dump(mode="json")}
    return json.dumps(body, indent=1, ensure_ascii=False, sort_keys=True) + "\n"


def load_presets(directory: Path) -> list[Preset]:
    """The presets on disk, in ``PRESET_IDS`` order; missing files are skipped."""
    out = []
    for qid in PRESET_IDS:
        path = directory / f"{qid}.json"
        if path.is_file():
            raw = json.loads(path.read_text())
            record = RunRecord.model_validate(raw["record"])
            out.append(Preset(raw["id"], raw["subtype"], record.question, record))
    return out


def replay(preset: Preset, graph: LineageGraph, project_dir: Path) -> tuple[AgentRun, Toolbox]:
    """Rebuild the run and its ledger: the recorded tool calls are re-run on the graph (pure
    code, deterministic); the model's turns come from the record. No LLM call."""
    box = Toolbox(graph, project_dir)
    for step in preset.record.steps:
        for r in step.results:
            if not r.deduped:
                box.call(r.tool, r.args, code=step.phase == "code")
    answer = Answer.model_validate(preset.record.final_answer)
    return AgentRun(answer=answer, record=preset.record), box
