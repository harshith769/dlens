"""Project mode of the local UI (``dlens ui --project DIR``, S14 E2): pure helpers, no Streamlit.

The app is the same ``app.py``; ``DLENS_UI_PROJECT`` (and ``DLENS_UI_TARGET``) switch it to one
project ingested with ``dlens ingest --artifacts``. The graph is read from ``<target>/dlens/``
and never built here. Explore, Trace/Impact and Source need no LLM.

Ask is isolated from the benchmark: the client env is a fresh dict (never ``os.environ``), so no
ambient key is picked up and the cache, quota counter and run logs live under
``<target>/dlens/ui/``. A user key lives only in a :class:`Secret` for the length of one ask.
"""

from __future__ import annotations

import importlib.util
import json
import re
import sys
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any, Literal

from dlens.agent.answer import Answer
from dlens.agent.llm.ollama import DEFAULT_MODEL as OLLAMA_MODEL
from dlens.agent.loop import AgentRun
from dlens.agent.runlog import RunLogger, RunRecord
from dlens.agent.tools.provenance import graph_files, safe_read
from dlens.graph import LineageGraph
from dlens.graph.cache import artifact_cache_dir, load_artifact_cache
from dlens.graph.report import COVERAGE_LEVELS, Coverage
from dlens.ingest import ArtifactError
from dlens.ui.view import Hint

if TYPE_CHECKING:
    from dlens.retrieval.index import SearchIndex

PROJECT_ENV = "DLENS_UI_PROJECT"
TARGET_ENV = "DLENS_UI_TARGET"
PRIVACY = "Your code stays on this machine unless you configure a cloud provider."
APP = Path(__file__).with_name("app.py")
LOCAL_HOSTS = ("127.0.0.1", "localhost", "::1")
INSTALL_UI = ('pipx install "dlens-lineage[ui]"', 'pip install "dlens-lineage[ui]"')
INSTALL_AGENT = (
    'pipx install --force "dlens-lineage[ui,agent]"',
    'pip install "dlens-lineage[agent]"',
)
INSTALL_RETRIEVAL = 'pip install "dlens-lineage[retrieval]"'


# -- where the project is ---------------------------------------------------------------------


@dataclass(frozen=True)
class Location:
    project_dir: Path
    target_dir: Path

    @property
    def name(self) -> str:
        """The ``name:`` of ``dbt_project.yml``, else the folder name."""
        return dbt_project_name(self.project_dir) or self.project_dir.name or str(self.project_dir)

    @property
    def folder(self) -> str:
        """The project folder for display, with the home directory shown as ``~``."""
        try:
            return "~/" + self.project_dir.relative_to(Path.home()).as_posix()
        except ValueError:
            return self.project_dir.as_posix()

    def rel(self, path: Path) -> str:
        """``path`` relative to the project folder when it is inside it (what a command run from
        the project folder needs), else the absolute path."""
        try:
            return path.relative_to(self.project_dir).as_posix() or "."
        except ValueError:
            return path.as_posix()

    @property
    def target(self) -> str:
        """The target directory as commands run from the project folder name it."""
        return self.rel(self.target_dir)

    @property
    def cache_dir(self) -> Path:
        return artifact_cache_dir(self.target_dir)

    @property
    def ui_dir(self) -> Path:
        """Everything Ask writes: LLM cache, quota counter, run logs."""
        return self.cache_dir / "ui"


_NAME = re.compile(r"""^name:\s*['"]?([A-Za-z0-9_.-]+)['"]?\s*(?:#.*)?$""", re.M)


def dbt_project_name(project_dir: Path) -> str | None:
    """``name:`` from ``dbt_project.yml`` (a top-level key; no YAML library needed)."""
    try:
        text = (project_dir / "dbt_project.yml").read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None
    m = _NAME.search(text)
    return m.group(1) if m else None


def locate(project: Path, artifacts: Path | None = None) -> Location:
    project = project.expanduser().resolve()
    target = (artifacts.expanduser() if artifacts is not None else project / "target").resolve()
    return Location(project, target)


def from_env(env: Mapping[str, str]) -> Location | None:
    """The project the app was launched on, or None outside project mode."""
    if not env.get(PROJECT_ENV):
        return None
    target = env.get(TARGET_ENV)
    return locate(Path(env[PROJECT_ENV]), Path(target) if target else None)


def launch_env(loc: Location) -> dict[str, str]:
    return {PROJECT_ENV: str(loc.project_dir), TARGET_ENV: str(loc.target_dir)}


def launch_command(port: int, host: str | None = None) -> list[str]:
    """Streamlit on loopback, headless, with Streamlit's usage statistics off (no telemetry)."""
    return [
        sys.executable,
        "-m",
        "streamlit",
        "run",
        str(APP),
        "--server.address",
        host or LOCAL_HOSTS[0],
        "--server.port",
        str(port),
        "--server.headless",
        "true",
        "--browser.gatherUsageStats",
        "false",
    ]


def has_module(name: str) -> bool:
    """``name`` is importable (a missing parent package or a blocked import counts as absent)."""
    try:
        return importlib.util.find_spec(name) is not None
    except (ImportError, ValueError):
        return False


class ProjectProblem(Exception):
    def __init__(self, hint: Hint) -> None:
        super().__init__(hint.title)
        self.hint = hint


def _ingest_cmd(loc: Location) -> str:
    return f"dlens ingest --artifacts {loc.target}"


def _run_in(loc: Location) -> str:
    return f"Run in the project folder ({loc.folder}):"


def load(loc: Location) -> LineageGraph:
    """The ingested graph; raises :class:`ProjectProblem` saying exactly what to run."""
    if not loc.project_dir.is_dir():
        raise ProjectProblem(
            Hint(f"Project folder not found: {loc.project_dir}", "Pass your dbt project folder.")
        )
    if not (loc.target_dir / "manifest.json").is_file():
        raise ProjectProblem(
            Hint(
                f"No dbt artifacts in {loc.target}",
                "Compile the project and write its catalog with dbt, then ingest it with DLens "
                f"(reads files only; no network). {_run_in(loc)}",
                ("dbt compile && dbt docs generate", _ingest_cmd(loc)),
            )
        )
    try:
        return load_artifact_cache(loc.target_dir)
    except ArtifactError as e:
        raise ProjectProblem(
            Hint(
                "This project is not ingested yet",
                f"{str(e).replace(str(loc.target_dir), loc.target)} {_run_in(loc)}",
                (_ingest_cmd(loc),),
            )
        ) from e


def problem(loc: Location) -> Hint | None:
    try:
        load(loc)
    except ProjectProblem as e:
        return e.hint
    return None


# -- explore and source (no LLM) -----------------------------------------------------------------


def model_rows(graph: LineageGraph, coverage: Coverage) -> list[dict[str, Any]]:
    """One row per parsed model (``coverage_summary`` levels, as ``dlens ingest`` prints them),
    worst first."""
    worse = {m.model: m for m in coverage.models}
    order = {lvl: i for i, lvl in enumerate(reversed(COVERAGE_LEVELS))}
    rows = []
    for uid in graph.parse_details():
        info = graph.model_info(uid) or {}
        m = worse.get(uid)
        rows.append(
            {
                "Model": info.get("name", uid),
                "Parse": m.level if m else "FULL",
                "Why": ", ".join(f"{k} ×{n}" for k, n in m.reasons.items()) if m else "",
                "File": info.get("file", ""),
            }
        )
    return sorted(rows, key=lambda r: (order[r["Parse"]], r["Model"]))


def full_share(coverage: Coverage) -> float:
    total = sum(coverage.counts.values())
    return coverage.counts.get("FULL", 0) / total if total else 0.0


def column_rows(graph: LineageGraph, uid: str) -> list[dict[str, Any]]:
    g = graph.nx_graph
    return [
        {
            "Column": g.nodes[c].get("name", c),
            "Type": g.nodes[c].get("type") or "",
            "Upstream edges": g.in_degree(c),
            "Downstream edges": g.out_degree(c),
        }
        for c in sorted(graph.columns())
        if graph.model_of(c) == uid
    ]


def default_column(graph: LineageGraph, options: Mapping[str, str]) -> int:
    """Index in ``options`` (display name -> column id, in their stable order) of the first
    column with upstream or downstream lineage; 0 if none has any."""
    g = graph.nx_graph
    return next(
        (i for i, col in enumerate(options.values()) if g.in_degree(col) or g.out_degree(col)), 0
    )


def source_files(graph: LineageGraph) -> list[str]:
    """The files the Source tab may show: exactly the ones the graph names."""
    return sorted(graph_files(graph))


def read_source(loc: Location, graph: LineageGraph, file: str) -> str | None:
    """A graph file, read-only, never outside the project (``safe_read``); None otherwise."""
    allowed = graph_files(graph)
    if file not in allowed:
        return None
    return safe_read(loc.project_dir, file, allowed)


def compiled_file(graph: LineageGraph, file: str) -> str | None:
    """``target/compiled/<package>/<path>`` for a model file, relative to the target."""
    uid = next(
        (u for u in graph.model_ids() if (graph.model_info(u) or {}).get("file") == file), None
    )
    if uid is None or not uid.startswith("model.") or not file.endswith(".sql"):
        return None
    package = uid.split(".")[1]
    prefix = f"dbt_packages/{package}/"
    rel = file[len(prefix) :] if file.startswith(prefix) else file
    return f"compiled/{package}/{rel}"


def read_compiled(loc: Location, graph: LineageGraph, file: str) -> str | None:
    rel = compiled_file(graph, file)
    return None if rel is None else safe_read(loc.target_dir, rel)


def example_questions(graph: LineageGraph, n: int = 2) -> list[str]:
    """Questions computed from the graph: end columns to trace, start columns to impact."""
    g = graph.nx_graph
    cols = sorted(graph.columns(), key=graph.display_name)
    ends = [c for c in cols if g.in_degree(c) and not g.out_degree(c)]
    starts = [c for c in cols if g.out_degree(c) and not g.in_degree(c)]
    return [
        *(f"Where does {graph.display_name(c)} come from?" for c in ends[:n]),
        *(f"What is affected if {graph.display_name(c)} changes?" for c in starts[:n]),
    ]


# -- Ask: provider, key, isolation ---------------------------------------------------------------

Kind = Literal["ollama", "gemini", "openai"]
KINDS: dict[Kind, str] = {
    "ollama": "Local model (Ollama)",
    "gemini": "Gemini (your key)",
    "openai": "OpenAI-compatible (your key)",
}
GEMINI_MODEL = "gemini-3.5-flash-lite"
DAILY_BUDGET = 50
_OPENAI_KEY_VAR = "DLENS_UI_OPENAI_KEY"  # set only in the per-ask env dict, never in os.environ
REDACTED = "[redacted]"


class Secret:
    """A key held in memory only. ``repr``/``str`` never show it; it cannot be pickled."""

    __slots__ = ("_value",)

    def __init__(self, value: str) -> None:
        self._value = value.strip()

    def reveal(self) -> str:
        return self._value

    def __bool__(self) -> bool:
        return bool(self._value)

    def __repr__(self) -> str:
        return "Secret(***)"

    __str__ = __repr__

    def __reduce__(self) -> Any:
        raise TypeError("a Secret cannot be pickled")


@dataclass(frozen=True)
class ProviderChoice:
    """What the Ask panel picked. Holds no key: only the *name* of a variable that holds one."""

    kind: Kind = "ollama"
    model: str = ""
    base_url: str = ""
    budget: int = DAILY_BUDGET
    key_env: str = ""

    @property
    def cloud(self) -> bool:
        if self.kind == "ollama":
            return False
        if self.kind == "openai":
            from urllib.parse import urlparse

            return (urlparse(self.base_url).hostname or "") not in LOCAL_HOSTS
        return True

    @property
    def label(self) -> str:
        return KINDS[self.kind]


def resolve_key(choice: ProviderChoice, typed: str, environ: Mapping[str, str]) -> Secret | None:
    """The key typed in the session, else the variable the user named; never an ambient key."""
    if typed.strip():
        return Secret(typed)
    if choice.key_env.strip() and environ.get(choice.key_env.strip()):
        return Secret(environ[choice.key_env.strip()])
    return None


def isolation_env(loc: Location) -> dict[str, str]:
    ui = loc.ui_dir
    return {
        "DLENS_CACHE_DIR": str(ui / "cache"),
        "DLENS_STATE_DIR": str(ui / "state"),
        "DLENS_RUN_DIR": str(ui / "runs"),
    }


def provider_env(choice: ProviderChoice, secret: Secret | None, loc: Location) -> dict[str, str]:
    """A fresh env for ``make_client``: only what the panel set plus the UI-only directories."""
    env = isolation_env(loc)
    env["DLENS_PROVIDER"] = choice.kind
    if choice.kind == "ollama":
        env["OLLAMA_MODEL"] = choice.model or OLLAMA_MODEL
    elif choice.kind == "gemini":
        env["DLENS_GEMINI_MODEL"] = choice.model or GEMINI_MODEL
        env["GEMINI_DAILY_BUDGET"] = str(choice.budget)
        if secret:
            env["GEMINI_API_KEY"] = secret.reveal()
    else:
        env["DLENS_OPENAI_BASE_URL"] = choice.base_url
        env["DLENS_OPENAI_MODEL"] = choice.model
        env["DLENS_OPENAI_DAILY_BUDGET"] = str(choice.budget)
        if secret:
            env["DLENS_OPENAI_KEY_ENV"] = _OPENAI_KEY_VAR
            env[_OPENAI_KEY_VAR] = secret.reveal()
    return env


_NEEDS: dict[Kind, tuple[str, ...]] = {
    "ollama": ("ollama",),
    "gemini": ("google.genai", "httpx"),
    "openai": ("httpx",),
}


def missing_extra(kind: Kind) -> Hint | None:
    """Ask needs the agent extra (the provider's client library); the other tabs never do."""
    missing = [m for m in _NEEDS[kind] if not has_module(m)]
    if not missing:
        return None
    return Hint(
        "Ask needs the agent extra",
        f"Not installed: {', '.join(missing)}. Install the extra, then restart `dlens ui`. "
        "Explore, Trace / Impact and Source work without it.",
        INSTALL_AGENT,
    )


def ask_problem(choice: ProviderChoice, secret: Secret | None) -> Hint | None:
    """Why Ask cannot run with this choice (missing extra, key, model or URL), else None."""
    if (hint := missing_extra(choice.kind)) is not None:
        return hint
    if choice.kind == "gemini" and not secret:
        return Hint(
            "No Gemini key",
            "Paste a key, or name the environment variable that holds it. DLens never reads "
            "GEMINI_API_KEY on its own.",
        )
    if choice.kind == "openai" and not (choice.base_url.strip() and choice.model.strip()):
        return Hint("Endpoint incomplete", "Enter the base URL and the model ID.")
    if choice.kind == "openai" and choice.cloud and not secret:
        return Hint("No API key", "Paste a key, or name the environment variable that holds it.")
    return None


def redact(text: str, secrets: Iterable[Secret | None]) -> str:
    for s in secrets:
        if s and len(s.reveal()) >= 4:
            text = text.replace(s.reveal(), REDACTED)
    return text


def scrub_run(run: AgentRun, secrets: Iterable[Secret | None]) -> AgentRun:
    """``run`` with every secret replaced (a provider that echoes the key never shows it)."""
    keys = [s for s in secrets if s]
    rec, ans = run.record.model_dump_json(), run.answer.model_dump_json()
    if redact(rec, keys) == rec and redact(ans, keys) == ans:
        return run
    return AgentRun(
        Answer.model_validate_json(redact(ans, keys)),
        RunRecord.model_validate_json(redact(rec, keys)),
        run.log_path,
    )


class RedactingRunLogger(RunLogger):
    """The agent's run logger, with every secret replaced before the record reaches disk."""

    def __init__(self, directory: Path, secrets: Iterable[Secret | None] = ()) -> None:
        super().__init__(directory)
        self._secrets = [s for s in secrets if s]

    def write(self, record: RunRecord) -> Path:
        raw = record.model_dump_json()
        clean = redact(raw, self._secrets)
        return super().write(record if clean == raw else RunRecord.model_validate_json(clean))


# -- docs search (optional) ----------------------------------------------------------------------

RETRIEVAL_MODULES = ("bm25s", "onnxruntime", "tokenizers")


def open_index(loc: Location, graph: LineageGraph) -> tuple[SearchIndex | None, str]:
    """The search index if the retrieval extra is installed and an index was built; else None
    and why. Ask then runs with the graph tools only (as S4 does without the hybrid stage)."""
    off = "Docs search off, Ask uses the graph tools only"
    if not all(has_module(m) for m in RETRIEVAL_MODULES):
        return None, f"{off}: the retrieval extra is not installed ({INSTALL_RETRIEVAL})."
    index_dir = loc.cache_dir / "index"
    if not index_dir.is_dir():
        return None, (
            f"{off}: no search index yet. Build it once with "
            f"`dlens search --artifacts {loc.target} orders` in the project folder."
        )
    try:
        from dlens.retrieval.dense import get_embedder, require_extra
        from dlens.retrieval.index import SearchIndex

        require_extra()
        meta = json.loads((loc.cache_dir / "meta.json").read_text(encoding="utf-8"))
        project = loc.project_dir if (loc.project_dir / "dbt_project.yml").is_file() else None
        index, status = SearchIndex.open(
            graph=graph,
            graph_file=loc.cache_dir / "graph.json",
            target_dir=loc.target_dir,
            project_dir=project,
            index_dir=index_dir,
            embedder=get_embedder(),
            dialect=str(meta["dialect"]),
        )
    except Exception as e:  # any failure: graph tools only, and say why
        return None, f"{off}: {type(e).__name__}: {e}"
    return index, f"Docs search on ({status})."
