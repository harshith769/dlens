"""Shared plumbing: structured errors, argument coercion, the payload/side-record pair."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from dlens.graph import AmbiguousColumn, ColumnNotFound, Hop, LineageGraph
from dlens.lineage import Edge


class ToolError(Exception):
    """Becomes ``{"error": {...}}``; tools never let it escape to the LLM as an exception."""

    def __init__(self, code: str, message: str, **extra: Any) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.extra = extra

    def payload(self) -> dict[str, Any]:
        return {"error": {"code": self.code, "message": self.message, **self.extra}}


@dataclass
class ToolOutput:
    """``payload`` is exactly what the LLM sees (capped). ``side`` holds the full records
    (edge objects, citations) that code, the validator and the UI use; the LLM never types them."""

    payload: dict[str, Any]
    side: dict[str, Any] = field(default_factory=dict)


def as_int(args: dict[str, Any], name: str, default: int, lo: int, hi: int) -> int:
    value = args.get(name, default)
    if isinstance(value, str) and value.strip().lstrip("-").isdigit():
        value = int(value)
    if isinstance(value, bool) or not isinstance(value, int) or not lo <= value <= hi:
        raise ToolError("invalid_argument", f"{name} must be an integer from {lo} to {hi}")
    return value


def as_bool(args: dict[str, Any], name: str, default: bool) -> bool:
    value = args.get(name, default)
    if isinstance(value, str) and value.lower() in ("true", "false"):
        value = value.lower() == "true"
    if not isinstance(value, bool):
        raise ToolError("invalid_argument", f"{name} must be true or false")
    return value


def as_str(args: dict[str, Any], name: str, *, required: bool = True) -> str | None:
    value = args.get(name)
    if value is None and not required:
        return None
    if not isinstance(value, str) or not value.strip():
        raise ToolError("invalid_argument", f"{name} must be a non-empty string")
    return value.strip()


def resolve_column(graph: LineageGraph, text: str) -> str:
    try:
        return graph.resolve(text)
    except ColumnNotFound as e:
        raise ToolError("unknown_column", str(e), suggestions=e.suggestions) from None
    except AmbiguousColumn as e:
        raise ToolError(
            "ambiguous", str(e), candidates=[graph.display_name(c) for c in e.candidates]
        ) from None


def direct(hop: Hop) -> Edge:
    """The tools traverse direct edges only (``include_indirect=False`` until S10/S12)."""
    if not isinstance(hop, Edge):
        raise TypeError(f"indirect hop in a direct-only tool: {hop.from_column} -> {hop.to_column}")
    return hop
