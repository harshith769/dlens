"""ToolSpec definitions shown to the LLM.

Kept short on purpose: specs ride along on every tool-phase call, inside the ~3K input cap. Only
the arguments a model needs are advertised; the tools still accept ``k`` (resolve_entity) and
``include_indirect`` (trace/impact) with their spec §8 defaults.
"""

from __future__ import annotations

from dlens.agent.llm.types import ToolSpec

_COLUMN = {"type": "string", "description": "model.column id, e.g. fct_orders.revenue_finance"}
_DEPTH = {"type": "integer", "description": "max hops, default 10"}

TOOL_SPECS: list[ToolSpec] = [
    ToolSpec(
        name="resolve_entity",
        description=(
            "Map a name or phrase to candidate column/model ids (handles case, abbreviations)."
        ),
        parameters={
            "type": "object",
            "properties": {"text": {"type": "string"}},
            "required": ["text"],
        },
    ),
    ToolSpec(
        name="trace_upstream",
        description="Where a column comes from: paths of edges 'e_xxxxxxxx: a -> b [KIND]'.",
        parameters={
            "type": "object",
            "properties": {"column_id": _COLUMN, "max_depth": _DEPTH},
            "required": ["column_id"],
        },
    ),
    ToolSpec(
        name="impact_downstream",
        description="What a column feeds: columns by depth (with edge id), models, exposures.",
        parameters={
            "type": "object",
            "properties": {"column_id": _COLUMN, "max_depth": _DEPTH},
            "required": ["column_id"],
        },
    ),
    ToolSpec(
        name="get_model_sql",
        description=(
            "Numbered source SQL of a model; around_column narrows to that column. "
            "Returns excerpt_id."
        ),
        parameters={
            "type": "object",
            "properties": {"model_id": {"type": "string"}, "around_column": {"type": "string"}},
            "required": ["model_id"],
        },
    ),
]
