"""Keep a tool payload under the token cap by dropping a prefix-ordered tail."""

from __future__ import annotations

import json
from collections.abc import Callable
from typing import Any

from dlens.agent.llm.tokens import estimate_tokens
from dlens.agent.llm.types import Message

MAX_RESULT_TOKENS = 1500


def payload_json(payload: dict[str, Any]) -> str:
    return json.dumps(payload, ensure_ascii=False, separators=(",", ":"))


def payload_tokens(payload: dict[str, Any]) -> int:
    return estimate_tokens([Message(role="tool", content=payload_json(payload))])


def largest_fit(n: int, render: Callable[[int], dict[str, Any]], cap: int) -> int:
    """Largest k in [0, n] with ``render(k)`` within the cap (size grows with k); 0 if none."""
    lo, hi = 0, n
    while lo < hi:
        mid = (lo + hi + 1) // 2
        if payload_tokens(render(mid)) <= cap:
            lo = mid
        else:
            hi = mid - 1
    return lo
