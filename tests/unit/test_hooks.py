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


# ------------------------------------------------------------------ precommit.py (S09 step 0)
PRECOMMIT = HOOK.with_name("precommit.py")


def _commit_gate(
    project: Path, command: str, tool: str = "Bash"
) -> subprocess.CompletedProcess[str]:
    payload = json.dumps({"tool_name": tool, "tool_input": {"command": command}})
    return subprocess.run(
        [sys.executable, str(PRECOMMIT)],
        input=payload,
        capture_output=True,
        text=True,
        env={**os.environ, "CLAUDE_PROJECT_DIR": str(project)},
        check=False,
    )


def _project(tmp_path: Path, lint: int, test: int) -> Path:
    (tmp_path / "Makefile").write_text(
        f"lint:\n\t@echo linting; exit {lint}\n"
        f"test:\n\t@echo testing; touch ran_test; exit {test}\n"
    )
    return tmp_path


def test_commit_blocked_when_tests_fail(tmp_path: Path) -> None:
    r = _commit_gate(_project(tmp_path, 0, 1), 'git commit -m "x"')
    assert r.returncode == 2
    assert "make test" in r.stderr and "testing" in r.stderr


def test_commit_blocked_when_lint_fails_and_tests_not_run(tmp_path: Path) -> None:
    r = _commit_gate(_project(tmp_path, 1, 0), "git add -A && git commit -m x")
    assert r.returncode == 2
    assert "make lint" in r.stderr
    assert not (tmp_path / "ran_test").exists()


def test_commit_allowed_when_both_pass(tmp_path: Path) -> None:
    r = _commit_gate(_project(tmp_path, 0, 0), "git -C repo commit --amend --no-edit")
    assert r.returncode == 0
    assert (tmp_path / "ran_test").exists()


def test_other_commands_do_not_run_make(tmp_path: Path) -> None:
    project = _project(tmp_path, 1, 1)
    for cmd in ("git status", "git log --oneline", "echo commit", "git commit-tree abc"):
        assert _commit_gate(project, cmd).returncode == 0, cmd
    assert _commit_gate(project, "git commit", tool="Read").returncode == 0
    assert not (tmp_path / "ran_test").exists()
