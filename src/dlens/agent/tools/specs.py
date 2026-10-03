"""ToolSpec definitions shown to the LLM."""

from __future__ import annotations

from dlens.agent.llm.types import ToolSpec

_COLUMN = {
    "type": "string",
    "description": "Column id as returned by another tool, e.g. 'fct_orders.revenue_finance'.",
}


def _depth(default: int) -> dict[str, object]:
    return {
        "type": "integer",
        "minimum": 1,
        "maximum": 50,
        "description": f"Maximum number of model hops (default {default}).",
    }


TOOL_SPECS: list[ToolSpec] = [
    ToolSpec(
        name="resolve_entity",
        description=(
            "Find the columns or models a name refers to (handles case, underscores and "
            "abbreviations like amt, qty). Use it first when the user's wording is not an exact id."
        ),
        parameters={
            "type": "object",
            "properties": {
                "text": {"type": "string", "description": "The name or phrase to look up."},
                "k": {
                    "type": "integer",
                    "minimum": 1,
                    "maximum": 20,
                    "description": "Max results (default 5).",
                },
            },
            "required": ["text"],
        },
    ),
    ToolSpec(
        name="trace_upstream",
        description=(
            "Where does a column come from? Returns every path from the column back to its "
            "sources as edge lines starting 'e_xxxxxxxx'. Cite edges by that id."
        ),
        parameters={
            "type": "object",
            "properties": {
                "column_id": _COLUMN,
                "max_depth": _depth(10),
                "include_indirect": {
                    "type": "boolean",
                    "description": "Also follow join/filter/group keys (default false).",
                },
            },
            "required": ["column_id"],
        },
    ),
    ToolSpec(
        name="impact_downstream",
        description=(
            "What breaks if a column changes? Returns columns that read it by depth (each with "
            "the edge id that reaches it), plus affected models and exposures."
        ),
        parameters={
            "type": "object",
            "properties": {
                "column_id": _COLUMN,
                "max_depth": _depth(10),
                "include_indirect": {
                    "type": "boolean",
                    "description": "Also follow join/filter/group keys (default true).",
                },
            },
            "required": ["column_id"],
        },
    ),
    ToolSpec(
        name="get_model_sql",
        description=(
            "Show a model's source SQL with line numbers. Pass around_column to see just the "
            "lines that compute that column. Cite the excerpt by its excerpt_id."
        ),
        parameters={
            "type": "object",
            "properties": {
                "model_id": {"type": "string", "description": "Model name or unique id."},
                "around_column": {
                    "type": "string",
                    "description": "Optional column name inside that model.",
                },
            },
            "required": ["model_id"],
        },
    ),
]
