"""Every traversal call states whether it follows indirect edges (S04), and every direct-only call
site in ``src/`` carries a recorded decision (S12a, s12-design A5, ADR 0026).

``LineageGraph.upstream`` / ``downstream`` keep their spec §7 defaults (downstream follows
indirect edges by default), so a bare call could silently change what a caller sees. Every call
in the code we ship or run must pass ``include_indirect`` explicitly (a literal or a variable).
In ``src/`` a literal ``include_indirect=False`` is a decision to show direct lineage only, so it
must be in ``ALLOWLIST`` with its decision id; a new pin fails CI until it is recorded.

Recorded but not scanned (not an ``.upstream`` / ``.downstream`` call):
A5-R9-DIRECT-READING, ``agent/tools/reach.py::_shortest_direct``: the ``r_`` fact's direct
reading is the shortest path over ``nx_graph`` (DERIVES edges only), so the fact can state both
readings; its verdict uses direct + indirect hops.
"""

import ast
from pathlib import Path

REPO = Path(__file__).parents[2]
ROOTS = ("src", "scripts", "eval", "demo")

# (file, enclosing function) -> decision id (s12-design A5 / ADR 0026)
ALLOWLIST = {
    ("src/dlens/agent/loop.py", "_chain_end"): "A5-CHAIN",
    ("src/dlens/retrieval/chunks.py", "_graph_meta"): "A5-CHUNK-META",
    ("src/dlens/agent/tools/impact.py", "reached_columns"): "A5-IMPACT-DIRECT-LABEL",
}


def _calls(path: Path) -> list[tuple[str, int, bool, bool]]:
    """(enclosing function, line, passes include_indirect, passes a literal False) for every
    ``.upstream(`` / ``.downstream(`` call."""
    found = []

    def visit(node: ast.AST, func: str) -> None:
        for child in ast.iter_child_nodes(node):
            name = func
            if isinstance(child, ast.FunctionDef | ast.AsyncFunctionDef):
                name = child.name
            if (
                isinstance(child, ast.Call)
                and isinstance(child.func, ast.Attribute)
                and child.func.attr in ("upstream", "downstream")
            ):
                kw = [k for k in child.keywords if k.arg == "include_indirect"]
                literal_false = any(
                    isinstance(k.value, ast.Constant) and k.value.value is False for k in kw
                )
                found.append((func, child.lineno, bool(kw), literal_false))
            visit(child, name)

    visit(ast.parse(path.read_text(), filename=str(path)), "<module>")
    return found


def _scan(paths: list[Path]) -> list[tuple[str, bool]]:
    """(file:line, passes include_indirect) for every traversal call."""
    return [(f"{p.name}:{line}", explicit) for p in paths for _, line, explicit, _ in _calls(p)]


def shipped_files() -> list[Path]:
    return [p for root in ROOTS for p in sorted((REPO / root).rglob("*.py"))]


def test_every_traversal_call_passes_include_indirect() -> None:
    calls = _scan(shipped_files())
    assert calls, "the scan found no traversal call at all: is it looking in the right place?"
    bare = [where for where, explicit in calls if not explicit]
    assert bare == [], f"pass include_indirect= explicitly at: {bare}"


def test_every_direct_only_pin_in_src_has_a_recorded_decision() -> None:
    pins = {
        (p.relative_to(REPO).as_posix(), func)
        for p in sorted((REPO / "src").rglob("*.py"))
        for func, _, _, literal_false in _calls(p)
        if literal_false
    }
    assert pins - set(ALLOWLIST) == set(), "record a decision id for these direct-only pins"
    assert set(ALLOWLIST) - pins == set(), "stale allowlist entries: the pin is gone"


def test_the_scan_catches_a_bare_call(tmp_path: Path) -> None:
    f = tmp_path / "x.py"
    f.write_text("g.downstream(col, max_depth=3)\ng.upstream(col, include_indirect=False)\n")
    assert _scan([f]) == [("x.py:1", False), ("x.py:2", True)]


def test_the_scan_sees_literal_pins_and_their_function(tmp_path: Path) -> None:
    f = tmp_path / "y.py"
    f.write_text(
        "def a(g, c, flag):\n"
        "    g.downstream(c, include_indirect=False)\n"
        "    g.upstream(c, include_indirect=flag)\n"
        "    g.upstream(c, include_indirect=True)\n"
    )
    assert [(fn, lit) for fn, _, _, lit in _calls(f)] == [
        ("a", True),
        ("a", False),
        ("a", False),
    ]
