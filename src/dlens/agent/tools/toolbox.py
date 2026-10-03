"""Toolbox: dispatches tool calls and keeps the per-conversation ledger.

One Toolbox per question (or call ``reset()`` between questions; the agent loop must). The ledger
holds every id the LLM was actually shown, with its full record, so the validator can check
"every cited ID appears in a tool result from this conversation" and look up citations without
the LLM ever typing a file or line.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field

from dlens.agent.llm.types import ToolSpec
from dlens.agent.tools.budget import payload_json
from dlens.agent.tools.common import ToolError, ToolOutput
from dlens.agent.tools.entity import resolve_entity
from dlens.agent.tools.impact import impact_downstream
from dlens.agent.tools.provenance import Provenance
from dlens.agent.tools.specs import TOOL_SPECS
from dlens.agent.tools.sql import get_model_sql
from dlens.agent.tools.trace import trace_upstream
from dlens.graph import LineageGraph

_TOOLS = {
    "resolve_entity": resolve_entity,
    "trace_upstream": trace_upstream,
    "impact_downstream": impact_downstream,
    "get_model_sql": get_model_sql,
}


class ToolResult(BaseModel):
    """One logged call: ``{tool, args, llm_payload, side_records}``."""

    tool: str
    args: dict[str, Any]
    llm_payload: dict[str, Any]
    side_records: dict[str, Any] = Field(default_factory=dict)

    @property
    def content(self) -> str:
        """The exact string for the ``tool`` message."""
        return payload_json(self.llm_payload)

    @property
    def is_error(self) -> bool:
        return "error" in self.llm_payload


class Toolbox:
    def __init__(self, graph: LineageGraph, project_dir: Path) -> None:
        self.graph = graph
        self.project_dir = project_dir
        self._prov = Provenance(graph, project_dir)
        self.log: list[ToolResult] = []
        self._emitted: dict[str, dict[str, Any]] = {}

    def specs(self) -> list[ToolSpec]:
        return list(TOOL_SPECS)

    def reset(self) -> None:
        """Start a new conversation: forget emitted ids and the call log."""
        self.log.clear()
        self._emitted.clear()

    @property
    def emitted_ids(self) -> frozenset[str]:
        """Edge ids (``e_``) and excerpt ids (``s_``) shown to the LLM in this conversation."""
        return frozenset(self._emitted)

    def record(self, item_id: str) -> dict[str, Any] | None:
        """Full record (with citation) of an emitted id, or None if it was never emitted."""
        return self._emitted.get(item_id)

    def edge_string(self, eid: str) -> str | None:
        """The compact one-line form of an edge (as tools print it), or None for an unknown id."""
        edge = self._prov.edge_by_id(eid)
        return None if edge is None else self._prov.edge_string(edge)

    def call(self, name: str, args: dict[str, Any] | None = None) -> ToolResult:
        """Run a tool. Never raises: failures come back as ``{"error": {...}}`` payloads."""
        args = dict(args or {})
        tool = _TOOLS.get(name)
        try:
            if tool is None:
                raise ToolError("unknown_tool", f"no tool {name!r}", suggestions=sorted(_TOOLS))
            out: ToolOutput = tool(self._prov, args)
        except ToolError as e:
            out = ToolOutput(e.payload())
        result = ToolResult(tool=name, args=args, llm_payload=out.payload, side_records=out.side)
        if not result.is_error:
            shown = set(_ids_in(out.payload))
            for eid, rec in out.side.get("edges", {}).items():
                if eid in shown:
                    self._emitted[eid] = rec
            for sid, rec in out.side.get("excerpts", {}).items():
                if sid in shown:
                    self._emitted[sid] = rec
        self.log.append(result)
        return result


def _ids_in(payload: dict[str, Any]) -> list[str]:
    """Ids visible in a payload: edge ids in path strings / ``via`` fields, and ``excerpt_id``."""
    found: list[str] = []
    for path in payload.get("paths", []):
        found += [line.split(":", 1)[0] for line in path]
    for items in payload.get("columns_by_depth", {}).values():
        found += [it["via"] for it in items]
    if "excerpt_id" in payload:
        found.append(payload["excerpt_id"])
    return found
