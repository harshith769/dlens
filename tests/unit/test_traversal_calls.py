"""Every traversal call states whether it follows indirect edges (S04).

``LineageGraph.upstream`` / ``downstream`` keep their spec §7 defaults (downstream follows
indirect edges by default), so a bare call could silently change what a caller sees. Every call
in the code we ship or run must pass ``include_indirect`` explicitly."""

import ast
from pathlib import Path

REPO = Path(__file__).parents[2]
ROOTS = ("src", "scripts", "eval", "demo")


def _scan(paths: list[Path]) -> list[tuple[str, bool]]:
    """(file:line, passes include_indirect) for every ``.upstream(`` / ``.downstream(`` call."""
    found = []
    for path in paths:
        for node in ast.walk(ast.parse(path.read_text(), filename=str(path))):
            if (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Attribute)
                and node.func.attr in ("upstream", "downstream")
            ):
                explicit = any(k.arg == "include_indirect" for k in node.keywords)
                found.append((f"{path.name}:{node.lineno}", explicit))
    return found


def shipped_files() -> list[Path]:
    return [p for root in ROOTS for p in sorted((REPO / root).rglob("*.py"))]


def test_every_traversal_call_passes_include_indirect() -> None:
    calls = _scan(shipped_files())
    assert calls, "the scan found no traversal call at all: is it looking in the right place?"
    bare = [where for where, explicit in calls if not explicit]
    assert bare == [], f"pass include_indirect= explicitly at: {bare}"


def test_the_scan_catches_a_bare_call(tmp_path: Path) -> None:
    f = tmp_path / "x.py"
    f.write_text("g.downstream(col, max_depth=3)\ng.upstream(col, include_indirect=False)\n")
    assert _scan([f]) == [("x.py:1", False), ("x.py:2", True)]
