"""No absolute local paths in committed fixtures, reports, docs or corpora (CLAUDE.md rule).

Scans what is (or is about to be) committed: tracked and staged files, plus untracked files that
are not ignored, so a new doc is checked before its first `git add` (the commit hook runs this
suite before the commit command adds anything).

The patterns are never loosened. A known-safe mention is allowed only through ALLOWED: an
exact (file, substring) pair, so a new absolute path in the same file still fails.
"""

import re
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).parents[2]
SCANNED = ["tests/fixtures", "demo", "docs", "eval", "corpora", "README.md", "CHANGELOG.md"]
SUFFIXES = {".json", ".jsonl", ".yml", ".yaml", ".md", ".sql", ".txt", ".csv"}
# A drive letter must stand alone (C:\Users), so JSON-escaped text such as "totals:\n" is not one.
PATTERN = re.compile(r"/home/|/Users/|(?<![A-Za-z])[A-Za-z]:\\|/tmp/|file://")
ALLOWED = {
    # Upstream jaffle_shop README (vendored verbatim): the upstream author's example output.
    ("corpora/jaffle_shop/README.md", "/Users/dbeatty/.pyenv/shims/dbt"),
    ("corpora/jaffle_shop/README.md", "/Users/dbeatty/projects/jaffle_duck/venv/bin/dbt"),
    # A Windows path template with a placeholder user, not a real path.
    ("docs/setup/chatgpt-accounts-prompt.md", r"C:\Users\<me>\.wslconfig"),
    # Session reports live outside the repo; docs may name them.
    ("docs/explain/artifact-ingest.md", "/tmp/s06-report.md"),
}


def _git_files(root: Path, *extra: str) -> list[str]:
    out = subprocess.run(
        ["git", "ls-files", *extra, "--", *SCANNED],
        cwd=root,
        capture_output=True,
        text=True,
        check=True,
    ).stdout
    return out.splitlines()


def _to_commit(root: Path = ROOT) -> list[str]:
    """Tracked or staged files, plus untracked non-ignored ones, under SCANNED."""
    try:
        files = _git_files(root) + _git_files(root, "--others", "--exclude-standard")
    except (OSError, subprocess.CalledProcessError):
        pytest.skip("git is not available")
    return sorted({f for f in files if Path(f).suffix in SUFFIXES})


def _violations(rel: str, text: str) -> list[str]:
    found = []
    for n, line in enumerate(text.splitlines(), start=1):
        if PATTERN.search(line) and not any(f == rel and s in line for f, s in ALLOWED):
            found.append(f"{rel}:{n}: {line.strip()[:120]}")
    return found


def test_no_absolute_paths_in_committed_files() -> None:
    bad: list[str] = []
    for rel in _to_commit():
        path = ROOT / rel
        if path.is_file():
            bad += _violations(rel, path.read_text(encoding="utf-8", errors="replace"))
    assert not bad, "absolute local paths in committed files:\n" + "\n".join(bad)


@pytest.mark.parametrize(
    "line",
    [
        '"root_path": "/home/someone/proj"',
        "see /Users/x/dbt",
        r"C:\Users\x\proj",
        "written to /tmp/out.json",
        "file:///home/x",
        r"D:\data",
    ],
)
def test_pattern_catches_absolute_paths(line: str) -> None:
    assert _violations("tests/fixtures/x.json", line)


def test_json_escaped_newline_is_not_a_drive() -> None:
    assert not _violations("demo/presets/x.json", r'"text": "the following transformations:\n\n1."')


def test_allowlist_is_exact_per_file() -> None:
    line = "    /Users/dbeatty/.pyenv/shims/dbt"
    assert not _violations("corpora/jaffle_shop/README.md", line)
    assert _violations("corpora/synthetic_shop/README.md", line)


def _git(root: Path, *args: str) -> None:
    subprocess.run(["git", *args], cwd=root, check=True, capture_output=True)


def test_scan_includes_staged_and_untracked_but_not_ignored(tmp_path: Path) -> None:
    _git(tmp_path, "init", "-q")
    (tmp_path / "docs").mkdir()
    (tmp_path / ".gitignore").write_text("docs/ignored.md\n")
    for name in ("tracked.md", "staged.md", "untracked.md", "ignored.md"):
        (tmp_path / "docs" / name).write_text("x\n")
    _git(tmp_path, "add", "docs/tracked.md")
    _git(tmp_path, "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-q", "-m", "t")
    _git(tmp_path, "add", "docs/staged.md")
    assert _to_commit(tmp_path) == ["docs/staged.md", "docs/tracked.md", "docs/untracked.md"]
