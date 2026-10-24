"""`dlens ui --project` (S14 E2): the not-ingested message, the loopback launch without
telemetry, and the exact install command when Streamlit (or any other extra) is missing."""

import shutil
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest
from typer.testing import CliRunner

from dlens.cli import app
from dlens.graph import load_or_build_artifacts
from dlens.ui import project as proj

runner = CliRunner()
EPH = Path(__file__).parents[1] / "fixtures" / "artifacts" / "eph_shop"
OPTIONAL = ("streamlit", "ollama", "google", "httpx", "bm25s", "onnxruntime", "tokenizers")


@pytest.fixture
def eph(tmp_path: Path) -> Path:
    shutil.copytree(EPH, tmp_path / "eph_shop", symlinks=True)
    return tmp_path / "eph_shop"


@pytest.fixture
def launched(monkeypatch) -> list[tuple[list[str], dict[str, str]]]:
    calls: list[tuple[list[str], dict[str, str]]] = []

    def fake_call(cmd, env):
        calls.append((cmd, env))
        return 0

    monkeypatch.setattr(proj, "has_module", lambda name: True)
    monkeypatch.setattr(subprocess, "call", fake_call)
    return calls


def test_not_ingested_prints_the_command_and_does_not_launch(eph: Path, launched) -> None:
    r = runner.invoke(app, ["ui", "--project", str(eph)])
    assert r.exit_code == 2
    assert "This project is not ingested yet" in r.output
    assert "  dlens ingest --artifacts target" in r.output
    assert "Run in the project folder" in r.output
    assert launched == []


def test_launch_binds_loopback_headless_without_telemetry(eph: Path, launched, monkeypatch) -> None:
    monkeypatch.setenv("DLENS_DEMO", "1")
    load_or_build_artifacts(eph / "target")
    r = runner.invoke(app, ["ui", "--project", str(eph), "--port", "8611"])
    assert r.exit_code == 0, r.output
    assert "http://127.0.0.1:8611" in r.output and proj.PRIVACY in r.output
    assert "warning" not in r.output
    [(cmd, env)] = launched
    assert cmd == proj.launch_command(8611)
    for flag in (
        ["--server.address", "127.0.0.1"],
        ["--server.headless", "true"],
        ["--browser.gatherUsageStats", "false"],
    ):
        i = cmd.index(flag[0])
        assert cmd[i : i + 2] == flag
    assert env[proj.PROJECT_ENV] == str(eph.resolve())
    assert env[proj.TARGET_ENV] == str(eph.resolve() / "target")
    assert "DLENS_DEMO" not in env  # never the public demo's mode


def test_host_override_warns(eph: Path, launched) -> None:
    load_or_build_artifacts(eph / "target")
    r = runner.invoke(app, ["ui", "--project", str(eph), "--host", "0.0.0.0"])
    assert r.exit_code == 0, r.output
    assert "warning: binding to 0.0.0.0" in r.output
    [(cmd, _)] = launched
    assert cmd[cmd.index("--server.address") + 1] == "0.0.0.0"


def test_artifacts_option_points_at_another_target(tmp_path: Path, eph: Path, launched) -> None:
    other = tmp_path / "elsewhere"
    shutil.move(eph / "target", other)
    load_or_build_artifacts(other)
    r = runner.invoke(app, ["ui", "--project", str(eph), "--artifacts", str(other)])
    assert r.exit_code == 0, r.output
    assert launched[0][1][proj.TARGET_ENV] == str(other.resolve())


BLOCKED = textwrap.dedent(
    """
    import importlib.abc, sys
    BLOCK = set(sys.argv[1].split(","))

    class Block(importlib.abc.MetaPathFinder):
        def find_spec(self, name, path=None, target=None):
            if name.split(".")[0] in BLOCK:
                raise ModuleNotFoundError(f"No module named {name!r} (blocked)")
            return None

    sys.meta_path.insert(0, Block())
    from typer.testing import CliRunner
    from dlens.cli import app
    r = CliRunner().invoke(app, ["ui", "--project", sys.argv[2]])
    print(r.exit_code)
    print(r.output)
    """
)


def test_without_any_extra_cli_imports_and_names_the_install(eph: Path, tmp_path: Path) -> None:
    script = tmp_path / "blocked.py"
    script.write_text(BLOCKED)
    out = subprocess.run(
        [sys.executable, "-I", str(script), ",".join(OPTIONAL), str(eph)],
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert out.returncode == 0, out.stderr
    code, *lines = out.stdout.splitlines()
    assert code == "2"
    text = "\n".join(lines)
    assert "needs the ui extra" in text
    assert 'pipx install "dlens-lineage[ui]"' in text and 'pip install "dlens-lineage[ui]"' in text
