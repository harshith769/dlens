"""s12-design A2 condition: the agent decides from its own signals only. Nothing under
``src/dlens/agent`` imports from ``eval/`` (metrics, the system runners, the oracle) or the gold
spec, or names a path under ``eval/`` (question files, gold labels)."""

from __future__ import annotations

import ast
import re
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
AGENT = REPO / "src" / "dlens" / "agent"
BANNED_MODULES = ("metrics", "systems", "eval", "dlens_oracle", "dlens.gold_spec")
# "eval/" only at a path boundary, so "src/dlens/retrieval/x.py" does not match
EVAL_PATH = re.compile(r"""(?:^|[\s"'(/=])eval/""")
QUESTION_FILES = re.compile(r"\b(dev|test|external)\.jsonl\b")


def _banned(module: str) -> bool:
    return any(module == b or module.startswith(b + ".") for b in BANNED_MODULES)


def scan(text: str, name: str = "<text>") -> list[str]:
    """Problems in one Python source: banned imports and string literals naming eval/ paths."""
    out: list[str] = []
    for node in ast.walk(ast.parse(text, filename=name)):
        if isinstance(node, ast.Import):
            out += [f"{name}:{node.lineno} import {a.name}" for a in node.names if _banned(a.name)]
        elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
            if _banned(node.module):
                out.append(f"{name}:{node.lineno} from {node.module}")
            elif node.module == "dlens" and any(a.name == "gold_spec" for a in node.names):
                out.append(f"{name}:{node.lineno} from dlens import gold_spec")
        elif isinstance(node, ast.Constant) and isinstance(node.value, str):
            if EVAL_PATH.search(node.value) or QUESTION_FILES.search(node.value):
                out.append(f"{name}:{node.lineno} names {node.value[:60]!r}")
    return out


def test_agent_never_reads_eval_or_gold() -> None:
    files = sorted(AGENT.rglob("*.py"))
    assert len(files) > 10, "the scan found too few agent modules"
    problems = [p for f in files for p in scan(f.read_text(), f.relative_to(REPO).as_posix())]
    assert problems == []


def test_the_scan_catches_imports_and_paths() -> None:
    assert scan('p = "src/dlens/retrieval/x.py"') == []
    assert scan('p = "eval/questions/dev.jsonl"') != []
    assert scan('p = ROOT / "eval/runs"') != []
    assert scan('open("dev.jsonl")') != []
    assert scan("import metrics") != []
    assert scan("from systems.s1 import S1_SYSTEM") != []
    assert scan("from dlens.gold_spec import load") != []
    assert scan("from dlens import gold_spec") != []
    assert scan("from dlens.retrieval.citation import chunk_citation") == []
    assert scan('"evaluate the draft"') == []
