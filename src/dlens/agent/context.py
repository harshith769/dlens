"""Tool-phase budget manager: keep the chat history under the input cap without losing ids.

Older tool messages are replaced by digests, oldest first and the newest last:
  level 1  trace: edge lines deduplicated across paths; impact: ``column via e_id`` list;
           get_model_sql: excerpt_id + file + range (SQL text dropped); resolve: candidate ids
  level 2  as level 1, minus edge expressions and impact models/exposures
Every id the original payload showed survives both levels (``ID_RE`` finds the same set or more).
Error payloads are small and left as they are.
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Any

from dlens.agent.llm.tokens import estimate_tokens
from dlens.agent.llm.types import Message, ToolSpec
from dlens.agent.tools import ToolResult
from dlens.agent.tools.budget import payload_json

_EXPR = re.compile(r" \[(\w+):.*\]$")


def _strip_expr(line: str) -> str:
    return _EXPR.sub(r" [\1]", line)


def digest(result: ToolResult, level: int) -> dict[str, Any]:
    """A compact stand-in for a tool payload that keeps every id it showed."""
    p = result.llm_payload
    if result.is_error:
        return p
    out: dict[str, Any] = {"digest": level, "tool": result.tool}
    if result.tool == "trace_upstream":
        lines = list(dict.fromkeys(line for path in p.get("paths", []) for line in path))
        if level >= 2:
            lines = list(dict.fromkeys(_strip_expr(line) for line in lines))
        out |= {"column": p.get("column"), "edges": lines, "truncated": p.get("truncated", False)}
    elif result.tool == "impact_downstream":
        reached = [
            f"{it['id']} via {it['via']}"
            for items in p.get("columns_by_depth", {}).values()
            for it in items
        ]
        out |= {"column": p.get("column"), "reached": reached}
        if level < 2:
            out |= {"models": p.get("models", []), "exposures": p.get("exposures", [])}
    elif result.tool == "get_model_sql":
        out |= {
            "model": p.get("model"),
            "file": p.get("file"),
            "excerpt_id": p.get("excerpt_id"),
            "excerpt_range": p.get("excerpt_range"),
        }
    elif result.tool == "resolve_entity":
        out |= {
            "query": p.get("query"),
            "candidates": [c["id"] for c in p.get("candidates", [])],
            "ambiguous": p.get("ambiguous", False),
        }
    else:
        return p
    return out


@dataclass
class History:
    """Tool-phase messages plus, for each tool message, the result it shows and its level."""

    messages: list[Message]
    sources: dict[int, ToolResult] = field(default_factory=dict)
    levels: dict[int, int] = field(default_factory=dict)

    def add_tool(self, result: ToolResult, call_id: str, content: str | None = None) -> None:
        self.sources[len(self.messages)] = result
        self.levels[len(self.messages)] = 0
        self.messages.append(
            Message(
                role="tool",
                content=result.content if content is None else content,
                tool_call_id=call_id,
                name=result.tool,
            )
        )

    def tokens(self, tools: Sequence[ToolSpec] | None) -> int:
        return estimate_tokens(self.messages, tools)


def fit(
    history: History, tools: Sequence[ToolSpec] | None, cap: int, step: int
) -> tuple[bool, list[dict[str, Any]]]:
    """Compact tool messages until the next call fits under ``cap``. Returns (fits, compactions);
    each compaction is ``{step, message_index, tool, level, tokens_before, tokens_after}``."""
    compactions: list[dict[str, Any]] = []
    for level in (1, 2):
        for idx in sorted(history.sources):
            if history.tokens(tools) <= cap:
                return True, compactions
            result = history.sources[idx]
            if history.levels[idx] >= level or result.is_error:
                continue
            old = history.messages[idx]
            new = old.model_copy(update={"content": payload_json(digest(result, level))})
            before, after = estimate_tokens([old]), estimate_tokens([new])
            history.levels[idx] = level
            if after >= before:
                continue
            history.messages[idx] = new
            compactions.append(
                {
                    "step": step,
                    "message_index": idx,
                    "tool": result.tool,
                    "level": level,
                    "tokens_before": before,
                    "tokens_after": after,
                }
            )
    return history.tokens(tools) <= cap, compactions
