"""Input-token estimate for the per-call cap (ADR 0007)."""

from __future__ import annotations

import json
import math
from collections.abc import Sequence

from dlens.agent.llm.types import Message, ToolSpec

MAX_INPUT_TOKENS = 3000


def estimate_tokens(messages: Sequence[Message], tools: Sequence[ToolSpec] | None = None) -> int:
    """Conservative: serialised JSON length / 3. JSON and SQL run at 3-4 chars per token, so this
    slightly over-counts and never lets an oversize call through. No tokenizer needed."""
    payload = {
        "messages": [m.model_dump(mode="json") for m in messages],
        "tools": [t.model_dump(mode="json") for t in tools or []],
    }
    return math.ceil(len(json.dumps(payload, ensure_ascii=False)) / 3)
