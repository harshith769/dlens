"""Citation coverage (S06b): how many citations point at lines, and why the rest cite a whole file.

Counted the way a user gets them: columns and direct edges through ``Provenance`` (the same
re-check the agent and the UI apply, reading the files), indirect edges from their stored
``model_level_citation`` flag. ``line`` and ``star`` are line-level; ``model`` is a whole file.
Each model-level citation gets one reason, grouped so a summary stays a few lines long:

* ``no project files``: artifacts without a dbt project around them, nothing to read.
* ``file not found``: the cited file is missing or outside what DLens may read.
* ``seed (CSV, whole file by design)`` / ``YAML (source, whole file by design)``.
* ``SELECT built by a macro or Jinja``: no SELECT item in the source names the column.
* ``clause key written by a macro or Jinja``: the clause's lines don't hold its key.
* ``clause not in the source``: the clause wasn't found, or has no source lines.

S06 reported "60 FULL" for dbt_jira while every citation there was model-level; parse quality and
citation coverage are separate numbers, and this module is the second one.
"""

from __future__ import annotations

from pathlib import Path

from pydantic import BaseModel, Field

from dlens.agent.tools.provenance import Provenance
from dlens.graph.graph import LineageGraph

NO_PROJECT = "no project files"
NOT_FOUND = "file not found"
SEED = "seed (CSV, whole file by design)"
YAML = "YAML (source, whole file by design)"
NOT_LOCATED = "SELECT built by a macro or Jinja"
KEY_NOT_IN_LINES = "clause key written by a macro or Jinja"
NO_CLAUSE = "clause not in the source"


class LevelCounts(BaseModel):
    total: int = 0
    line: int = 0
    """Line-level, including ``star`` (the ``*`` that produced the column)."""
    model: int = 0
    reasons: dict[str, int] = Field(default_factory=dict)
    """Why each model-level citation is one, grouped (see the module docstring)."""

    @property
    def percent(self) -> float:
        return 100.0 * self.line / self.total if self.total else 100.0

    def add(self, line_level: bool, reason: str | None = None) -> None:
        self.total += 1
        if line_level:
            self.line += 1
            return
        self.model += 1
        key = reason or "other"
        self.reasons[key] = self.reasons.get(key, 0) + 1


class CitationCoverage(BaseModel):
    columns: LevelCounts
    """Columns of SQL models (what ``where is X computed`` cites)."""
    seed_source_columns: LevelCounts
    """Seed and source columns: always a whole CSV or YAML file, counted apart."""
    direct: LevelCounts
    indirect: LevelCounts


def _file_reason(prov: Provenance | None, file: str) -> str | None:
    """Why ``file`` can't give a line citation at all, or None if it can."""
    if prov is None:
        return NO_PROJECT
    if not file or prov.source(file) is None:
        return NOT_FOUND
    if file.endswith(".csv"):
        return SEED
    if not file.endswith(".sql"):
        return YAML
    return None


def _clause_reason(gap: str) -> str:
    """Group a ``ModelParse.citation_gaps`` reason (``locate_clause`` and the engine)."""
    if "source file not found" in gap:
        return NOT_FOUND
    if "not in source lines" in gap:
        return KEY_NOT_IN_LINES
    return NO_CLAUSE


def citation_coverage(graph: LineageGraph, project_dir: Path | None) -> CitationCoverage:
    """Line-level vs model-level citations for columns, direct and indirect edges.
    ``project_dir`` None: artifacts with no dbt project around them, so nothing can be read."""
    prov = Provenance(graph, project_dir) if project_dir is not None else None
    cov = CitationCoverage(
        columns=LevelCounts(),
        seed_source_columns=LevelCounts(),
        direct=LevelCounts(),
        indirect=LevelCounts(),
    )
    for col in graph.columns():
        file = (graph.model_info(graph.model_of(col)) or {}).get("file", "")
        counts = cov.columns if file.endswith(".sql") else cov.seed_source_columns
        line = prov is not None and prov.column_citation(col).level != "model"
        counts.add(line, None if line else _file_reason(prov, file) or NOT_LOCATED)
    for e in graph.edges():
        line = prov is not None and prov.edge_citation(e).level != "model"
        cov.direct.add(line, None if line else _file_reason(prov, e.file) or NOT_LOCATED)
    gaps = graph.parse_details()
    for ie in graph.indirect_edges():
        if prov is not None and not ie.model_level_citation:
            cov.indirect.add(True)
            continue
        reason = _file_reason(prov, ie.file)
        if reason is None:
            model = graph.model_of(ie.to_column)
            prefix = f"{ie.kind} {ie.expression}: "
            mine = gaps[model].citation_gaps if model in gaps else []
            found = [g for g in mine if g.startswith(prefix)]
            reason = _clause_reason(found[0]) if found else NO_CLAUSE
        cov.indirect.add(False, reason)
    for counts in (cov.columns, cov.seed_source_columns, cov.direct, cov.indirect):
        counts.reasons = dict(sorted(counts.reasons.items(), key=lambda kv: (-kv[1], kv[0])))
    return cov
