"""Project mode helpers (S14 E2): loading an ingested project, the not-ingested hints, path
safety, and key handling (a sentinel key never reaches a log, a dump or an error)."""

import os
import pickle
import shutil
from pathlib import Path

import pytest

from dlens.agent.runlog import RunRecord
from dlens.graph import load_or_build_artifacts
from dlens.graph.report import build_report
from dlens.ui import project as proj

EPH = Path(__file__).parents[3] / "fixtures" / "artifacts" / "eph_shop"
SENTINEL = "sk-SENTINEL-0123456789abcdef"


@pytest.fixture
def eph(tmp_path: Path) -> Path:
    dest = tmp_path / "eph_shop"
    shutil.copytree(EPH, dest, symlinks=True)
    return dest


@pytest.fixture
def ingested(eph: Path) -> proj.Location:
    load_or_build_artifacts(eph / "target")
    return proj.locate(eph)


def test_locate_defaults_to_project_target_and_round_trips_env(eph: Path) -> None:
    loc = proj.locate(eph)
    assert loc.target_dir == eph.resolve() / "target"
    assert loc.ui_dir == eph.resolve() / "target" / "dlens" / "ui"
    assert proj.from_env(proj.launch_env(loc)) == loc
    assert proj.from_env({}) is None


def test_load_ingested_project(ingested: proj.Location) -> None:
    graph = proj.load(ingested)
    assert "model.eph_shop.customer_summary" in graph.model_ids()
    assert proj.problem(ingested) is None


def test_not_ingested_shows_the_exact_command(eph: Path) -> None:
    hint = proj.problem(proj.locate(eph))
    assert hint is not None and hint.title == "This project is not ingested yet"
    assert hint.commands == (f"dlens ingest --artifacts {eph.resolve() / 'target'}",)


def test_no_artifacts_says_to_run_dbt_first(tmp_path: Path) -> None:
    (tmp_path / "p").mkdir()
    hint = proj.problem(proj.locate(tmp_path / "p"))
    assert hint is not None and "No dbt artifacts" in hint.title
    assert hint.commands[0].endswith("dbt compile && dbt docs generate")
    assert hint.commands[1].startswith("dlens ingest --artifacts ")


def test_missing_folder(tmp_path: Path) -> None:
    hint = proj.problem(proj.locate(tmp_path / "nope"))
    assert hint is not None and "not found" in hint.title


def test_stale_graph_is_not_ingested(ingested: proj.Location) -> None:
    manifest = ingested.target_dir / "manifest.json"
    manifest.write_text(manifest.read_text() + " ")
    hint = proj.problem(ingested)
    assert hint is not None and "stale" in hint.body


def test_explore_rows(ingested: proj.Location) -> None:
    graph = proj.load(ingested)
    report = build_report(graph)
    rows = proj.model_rows(graph, report)
    assert {r["Model"] for r in rows} >= {"customer_summary", "stg_customers"}
    assert sum(proj.quality_counts(report).values()) == len(report.models)
    cols = proj.column_rows(graph, "model.eph_shop.customer_summary")
    assert cols and all(
        set(c) == {"Column", "Type", "Upstream edges", "Downstream edges"} for c in cols
    )


def test_source_reads_only_graph_files_inside_the_project(
    ingested: proj.Location, tmp_path: Path
) -> None:
    graph = proj.load(ingested)
    files = proj.source_files(graph)
    assert "models/customer_summary.sql" in files
    assert proj.read_source(ingested, graph, "models/customer_summary.sql")
    outside = tmp_path / "secret.txt"
    outside.write_text("nope")
    (ingested.project_dir / "models" / "link.sql").symlink_to(outside)
    for bad in (
        "../secret.txt",
        str(outside),
        "models/../../secret.txt",
        "models/link.sql",
        "dbt_project.yml",  # inside the project, but not a graph file
    ):
        assert proj.read_source(ingested, graph, bad) is None, bad


def test_compiled_sql_for_project_and_package_models(ingested: proj.Location) -> None:
    graph = proj.load(ingested)
    assert proj.compiled_file(graph, "models/customer_summary.sql") == (
        "compiled/eph_shop/models/customer_summary.sql"
    )
    pkg = "dbt_packages/eph_pkg/models/pkg_customer_names.sql"
    assert proj.compiled_file(graph, pkg) == "compiled/eph_pkg/models/pkg_customer_names.sql"
    assert proj.compiled_file(graph, "seeds/raw_orders.csv") is None
    assert proj.read_compiled(ingested, graph, "models/customer_summary.sql")


def test_example_questions_come_from_the_graph(ingested: proj.Location) -> None:
    qs = proj.example_questions(proj.load(ingested))
    assert any(q.startswith("Where does ") for q in qs)
    assert any(q.startswith("What is affected if ") for q in qs)


def test_launch_command_binds_loopback_without_telemetry() -> None:
    cmd = proj.launch_command(8600)
    assert cmd[1:4] == ["-m", "streamlit", "run"] and cmd[4].endswith("dlens/ui/app.py")
    pairs = dict(zip(cmd[5::2], cmd[6::2], strict=True))
    assert pairs == {
        "--server.address": "127.0.0.1",
        "--server.port": "8600",
        "--server.headless": "true",
        "--browser.gatherUsageStats": "false",
    }
    assert "0.0.0.0" in proj.launch_command(8600, "0.0.0.0")


# -- keys -----------------------------------------------------------------------------------------


def test_secret_never_shows_itself() -> None:
    s = proj.Secret(f"  {SENTINEL} ")
    assert s.reveal() == SENTINEL
    for shown in (repr(s), str(s), f"{s}", repr([s]), repr({"k": s})):
        assert SENTINEL not in shown
    with pytest.raises(TypeError):
        pickle.dumps(s)


def test_key_comes_only_from_the_session_or_a_named_variable(monkeypatch) -> None:
    monkeypatch.setenv("GEMINI_API_KEY", SENTINEL)
    gemini = proj.ProviderChoice("gemini")
    assert proj.resolve_key(gemini, "", os.environ) is None  # never the ambient key
    hint = proj.ask_problem(gemini, None)
    if proj.missing_extra("gemini") is None:
        assert hint is not None and hint.title == "No Gemini key"
    named = proj.ProviderChoice("gemini", key_env="MY_KEY")
    monkeypatch.setenv("MY_KEY", "from-my-var")
    key = proj.resolve_key(named, "", os.environ)
    assert key is not None and key.reveal() == "from-my-var"
    typed = proj.resolve_key(named, "typed-key", os.environ)
    assert typed is not None and typed.reveal() == "typed-key"


def test_provider_env_is_fresh_and_isolated(eph: Path, monkeypatch) -> None:
    monkeypatch.setenv("GEMINI_API_KEY", "ambient")
    loc = proj.locate(eph)
    before = dict(os.environ)
    env = proj.provider_env(proj.ProviderChoice("gemini"), proj.Secret(SENTINEL), loc)
    assert dict(os.environ) == before  # never mutated
    assert env["GEMINI_API_KEY"] == SENTINEL and env["GEMINI_DAILY_BUDGET"] == "50"
    assert env["DLENS_GEMINI_MODEL"] == proj.GEMINI_MODEL
    for var in ("DLENS_CACHE_DIR", "DLENS_STATE_DIR", "DLENS_RUN_DIR"):
        assert Path(env[var]).is_relative_to(loc.ui_dir)
    assert "HOME" not in env and "PATH" not in env
    ollama = proj.provider_env(proj.ProviderChoice("ollama"), None, loc)
    assert "GEMINI_API_KEY" not in ollama and ollama["DLENS_PROVIDER"] == "ollama"
    openai = proj.provider_env(
        proj.ProviderChoice("openai", "m-1", "https://api.example.com/v1", budget=7),
        proj.Secret(SENTINEL),
        loc,
    )
    assert openai[openai["DLENS_OPENAI_KEY_ENV"]] == SENTINEL
    assert openai["DLENS_OPENAI_DAILY_BUDGET"] == "7"


def test_openai_choice_needs_url_model_and_a_key_off_loopback() -> None:
    if proj.missing_extra("openai") is not None:
        pytest.skip("needs httpx (agent extra)")
    assert proj.ask_problem(proj.ProviderChoice("openai"), None) is not None
    local = proj.ProviderChoice("openai", "m", "http://localhost:11434/v1")
    assert not local.cloud and proj.ask_problem(local, None) is None
    remote = proj.ProviderChoice("openai", "m", "https://api.example.com/v1")
    assert remote.cloud and proj.ask_problem(remote, None) is not None
    assert proj.ask_problem(remote, proj.Secret(SENTINEL)) is None


def test_missing_agent_extra_gives_install_commands(monkeypatch) -> None:
    monkeypatch.setattr(proj, "has_module", lambda name: False)
    hint = proj.missing_extra("ollama")
    assert hint is not None and hint.commands == proj.INSTALL_AGENT
    assert "ollama" in hint.body


def test_redact_and_scrub_run() -> None:
    from dlens.agent.answer import Answer
    from dlens.agent.loop import AgentRun

    s = proj.Secret(SENTINEL)
    assert proj.redact(f"401 for key {SENTINEL}", [s, None]) == "401 for key [redacted]"
    rec = RunRecord(run_id="r", started_at="2026-10-24T00:00:00+00:00", question="q")
    rec.error = f"ProviderError: bad key {SENTINEL}"
    answer = Answer(answer_text="", refused=True, refusal_reason=f"failed: {SENTINEL}")
    run = proj.scrub_run(AgentRun(answer, rec), [s])
    assert SENTINEL not in run.record.model_dump_json() + run.answer.model_dump_json()
    assert run.record.error == "ProviderError: bad key [redacted]"


def test_redacting_logger_never_writes_the_key(tmp_path: Path) -> None:
    rec = RunRecord(run_id="r", started_at="2026-10-24T00:00:00+00:00", question="q")
    rec.error = f"echoed {SENTINEL}"
    path = proj.RedactingRunLogger(tmp_path, [proj.Secret(SENTINEL)]).write(rec)
    text = path.read_text()
    assert SENTINEL not in text and "[redacted]" in text


def test_open_index_without_extra_or_index(ingested: proj.Location, monkeypatch) -> None:
    graph = proj.load(ingested)
    index, status = proj.open_index(ingested, graph)
    assert index is None and "graph tools only" in status
    monkeypatch.setattr(proj, "has_module", lambda name: False)
    index, status = proj.open_index(ingested, graph)
    assert index is None and "retrieval extra is not installed" in status
