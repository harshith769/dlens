import json
import os
import subprocess
import sys
from pathlib import Path

HOOK = Path(__file__).parents[2] / ".claude" / "hooks" / "format.py"


def _run(stdin: str, env: dict[str, str] | None = None) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(HOOK)],
        input=stdin,
        capture_output=True,
        text=True,
        env=env,
        check=False,
    )


def _payload(path: Path) -> str:
    return json.dumps({"tool_input": {"file_path": str(path)}})


def test_unfixable_lint_error_warns_and_exits_zero(tmp_path: Path) -> None:
    f = tmp_path / "bad.py"
    f.write_text("x = undefined_name\n")
    r = _run(_payload(f))
    assert r.returncode == 0
    assert "F821" in r.stderr
    assert r.stdout == ""


def test_unused_import_is_not_removed(tmp_path: Path) -> None:
    f = tmp_path / "imp.py"
    f.write_text("import os\n")
    r = _run(_payload(f))
    assert r.returncode == 0
    assert "import os" in f.read_text()


def test_missing_uv_warns_and_exits_zero(tmp_path: Path) -> None:
    f = tmp_path / "ok.py"
    f.write_text("x = 1\n")
    r = _run(_payload(f), env={**os.environ, "PATH": str(tmp_path)})
    assert r.returncode == 0
    assert "format hook" in r.stderr


def test_malformed_stdin_exits_zero() -> None:
    r = _run("not json")
    assert r.returncode == 0
    assert "format hook" in r.stderr


def test_non_python_path_is_silent(tmp_path: Path) -> None:
    r = _run(_payload(tmp_path / "notes.md"))
    assert (r.returncode, r.stdout, r.stderr) == (0, "", "")
