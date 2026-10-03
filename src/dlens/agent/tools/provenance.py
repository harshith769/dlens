"""Ids and citations that tool results carry (the contract the validator relies on).

* ``edge_id``: ``"e_" + sha1("from|to|kind")[:8]``, a pure function of the edge's content.
* ``excerpt_id``: ``"s_" + sha1("file|line_start|line_end")[:8]`` for a get_model_sql excerpt.
* ``Citation``: file (relative to the project root, the SOURCE .sql), line range, and a level:
  ``line``  the range contains the column name as a whole word;
  ``star``  the range holds the ``*`` that produced the column (name not written in the file);
  ``model`` the locator found nothing: the whole file is cited, no line is claimed.

Every citation is re-checked against the file text before it leaves this module and is downgraded
to ``model`` if it does not hold, so a citation never points at a line that lacks the evidence.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

from pydantic import BaseModel

from dlens.graph import LineageGraph
from dlens.lineage import Edge
from dlens.lineage.provenance import locate

Level = Literal["line", "star", "model"]
EXPRESSION_CHARS = 120


class Citation(BaseModel):
    file: str
    line_start: int
    line_end: int
    level: Level


def edge_id(edge: Edge) -> str:
    key = f"{edge.from_column}|{edge.to_column}|{edge.kind.value}"
    return "e_" + hashlib.sha1(key.encode()).hexdigest()[:8]


def excerpt_id(file: str, line_start: int, line_end: int) -> str:
    return "s_" + hashlib.sha1(f"{file}|{line_start}|{line_end}".encode()).hexdigest()[:8]


def safe_read(root: Path, file: str) -> str | None:
    """Text of ``file`` relative to ``root``, or None if it is missing or resolves outside ``root``
    (``../`` or symlink escapes). Always reads from disk: no cache."""
    if not file:
        return None
    base = root.resolve()
    path = (base / file).resolve()
    if not path.is_relative_to(base) or not path.is_file():
        return None
    return path.read_text(errors="replace")


def text_sha1(text: str, line_start: int, line_end: int) -> str:
    """sha1 of lines ``line_start..line_end`` (1-based, inclusive) joined by ``\\n``."""
    chunk = "\n".join(text.splitlines()[line_start - 1 : line_end])
    return hashlib.sha1(chunk.encode()).hexdigest()


def contains_word(text: str, word: str) -> bool:
    return re.search(rf"(?<!\w){re.escape(word)}(?!\w)", text, re.IGNORECASE) is not None


@dataclass
class Provenance:
    """Builds ids, citations and compact strings for one graph + project root."""

    graph: LineageGraph
    project_dir: Path
    _sources: dict[str, str | None] = field(default_factory=dict)
    _edge_ids: dict[str, Edge] = field(default_factory=dict)

    def __post_init__(self) -> None:
        for e in self.graph.edges():
            eid = edge_id(e)
            other = self._edge_ids.get(eid)
            if other is not None and other != e:
                raise ValueError(f"edge_id collision {eid}: {other} vs {e}")
            self._edge_ids[eid] = e

    # -- files ---------------------------------------------------------------------------------

    def source(self, file: str) -> str | None:
        """Text of a project file, or None if it is missing or outside the project root."""
        if file not in self._sources:
            self._sources[file] = safe_read(self.project_dir, file)
        return self._sources[file]

    @staticmethod
    def line_count(text: str) -> int:
        return max(1, text.count("\n") + (0 if text.endswith("\n") else 1))

    # -- citations -----------------------------------------------------------------------------

    def _checked(self, file: str, name: str, lines: tuple[int, int], model_level: bool) -> Citation:
        text = self.source(file)
        if text is None:
            return Citation(file=file, line_start=1, line_end=1, level="model")
        whole = Citation(file=file, line_start=1, line_end=self.line_count(text), level="model")
        if model_level:
            return whole
        a, b = lines
        total = self.line_count(text)
        if not 1 <= a <= b <= total:
            return whole
        chunk = "\n".join(text.splitlines()[a - 1 : b])
        if contains_word(chunk, name):
            return Citation(file=file, line_start=a, line_end=b, level="line")
        if "*" in chunk:
            return Citation(file=file, line_start=a, line_end=b, level="star")
        return whole

    def edge_citation(self, edge: Edge) -> Citation:
        name = self.graph.nx_graph.nodes[edge.to_column]["name"]
        return self._checked(edge.file, name, edge.lines, edge.model_level_citation)

    def column_citation(self, column: str) -> Citation:
        info = self.graph.model_info(self.graph.model_of(column)) or {}
        file = info.get("file", "")
        name = self.graph.nx_graph.nodes[column]["name"]
        text = self.source(file)
        if text is None or not file.endswith(".sql"):
            # Seeds and other non-SQL nodes: cite the file as a whole (a CSV header holds the name).
            end = self.line_count(text) if text is not None else 1
            return Citation(file=file, line_start=1, line_end=end, level="model")
        cite = locate(text, name)
        return self._checked(file, name, cite.lines, cite.model_level)

    # -- edges ---------------------------------------------------------------------------------

    def edge_by_id(self, eid: str) -> Edge | None:
        return self._edge_ids.get(eid)

    def edge_string(self, edge: Edge) -> str:
        """``e_1a2b3c4d: stg_orders.amount -> orders.amount [RENAME]``; transformations and
        aggregations append the expression (60 chars) so the model can say how it is computed."""
        g = self.graph
        src, dst = g.display_name(edge.from_column), g.display_name(edge.to_column)
        head = f"{edge_id(edge)}: {src} -> {dst}"
        kind = edge.kind.value
        if kind in ("TRANSFORMATION", "AGGREGATION"):
            expr = " ".join(edge.expression.split())
            if len(expr) > 60:
                expr = expr[:59] + "…"
            return f"{head} [{kind}: {expr}]"
        return f"{head} [{kind}]"

    def edge_record(self, edge: Edge) -> dict[str, object]:
        expr = " ".join(edge.expression.split())
        return {
            "edge_id": edge_id(edge),
            "from": edge.from_column,
            "to": edge.to_column,
            "kind": edge.kind.value,
            "expression": expr[: EXPRESSION_CHARS - 1] + "…"
            if len(expr) > EXPRESSION_CHARS
            else expr,
            "confidence": edge.confidence.value,
            "citation": self.edge_citation(edge).model_dump(),
        }
