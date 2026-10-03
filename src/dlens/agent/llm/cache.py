"""SQLite response cache. A hit means zero network calls and zero quota."""

from __future__ import annotations

import hashlib
import json
import sqlite3
import time
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from dlens.agent.llm.types import LLMResponse, Message, ToolSpec


def cache_key(
    provider: str,
    model: str,
    messages: Sequence[Message],
    tools: Sequence[ToolSpec] | None,
    params: Mapping[str, Any],
) -> str:
    blob = json.dumps(
        {
            "provider": provider,
            "model": model,
            "messages": [m.model_dump(mode="json") for m in messages],
            "tools": [t.model_dump(mode="json") for t in tools or []],
            "params": dict(params),
        },
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    )
    return hashlib.sha256(blob.encode()).hexdigest()


class ResponseCache:
    def __init__(self, path: Path):
        self.path = path
        path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as db:
            db.execute(
                "CREATE TABLE IF NOT EXISTS responses ("
                "key TEXT PRIMARY KEY, response_json TEXT NOT NULL, created_at REAL NOT NULL)"
            )

    def _connect(self) -> sqlite3.Connection:
        return sqlite3.connect(self.path, timeout=30)

    def get(self, key: str) -> LLMResponse | None:
        db = self._connect()
        try:
            row = db.execute("SELECT response_json FROM responses WHERE key = ?", (key,)).fetchone()
        finally:
            db.close()
        return LLMResponse.model_validate_json(row[0]) if row else None

    def put(self, key: str, response: LLMResponse) -> None:
        stored = response.model_copy(update={"cached": False})
        db = self._connect()
        try:
            with db:
                db.execute(
                    "INSERT OR REPLACE INTO responses VALUES (?, ?, ?)",
                    (key, stored.model_dump_json(), time.time()),
                )
        finally:
            db.close()
