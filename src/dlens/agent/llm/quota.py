"""Persisted per-provider daily call counter. The day rolls over at midnight US Pacific,
which is when Google resets RPD."""

from __future__ import annotations

import sqlite3
from collections.abc import Callable, Mapping
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from dlens.agent.llm.types import QuotaExceeded

PACIFIC = ZoneInfo("America/Los_Angeles")
DEFAULT_GEMINI_BUDGET = 400


def default_budgets(env: Mapping[str, str]) -> dict[str, int | None]:
    return {
        "gemini": int(env.get("GEMINI_DAILY_BUDGET") or DEFAULT_GEMINI_BUDGET),
        "groq": None,  # Groq is limited in tokens/day; added with the Groq adapter
        "ollama": None,
    }


def _now() -> datetime:
    return datetime.now(PACIFIC)


class QuotaCounter:
    def __init__(
        self,
        path: Path,
        budgets: Mapping[str, int | None],
        clock: Callable[[], datetime] = _now,
    ):
        self.path = path
        self.budgets = dict(budgets)
        self._clock = clock
        path.parent.mkdir(parents=True, exist_ok=True)
        db = self._connect()
        try:
            db.execute(
                "CREATE TABLE IF NOT EXISTS calls ("
                "provider TEXT, day TEXT, count INTEGER NOT NULL, PRIMARY KEY (provider, day))"
            )
        finally:
            db.close()

    def _connect(self) -> sqlite3.Connection:
        return sqlite3.connect(self.path, timeout=30, isolation_level=None)

    def _day(self) -> str:
        return self._clock().astimezone(PACIFIC).date().isoformat()

    def used(self, provider: str) -> int:
        db = self._connect()
        try:
            row = db.execute(
                "SELECT count FROM calls WHERE provider = ? AND day = ?", (provider, self._day())
            ).fetchone()
        finally:
            db.close()
        return int(row[0]) if row else 0

    def remaining(self, provider: str) -> int | None:
        """Calls left today, or None if the provider has no budget."""
        budget = self.budgets.get(provider)
        return None if budget is None else max(budget - self.used(provider), 0)

    def reserve(self, provider: str) -> None:
        """Atomically check the budget and count one call. Raises QuotaExceeded *before* the
        call is sent. The count includes calls that later fail: providers count those too."""
        budget = self.budgets.get(provider)
        day = self._day()
        db = self._connect()
        try:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute(
                "SELECT count FROM calls WHERE provider = ? AND day = ?", (provider, day)
            ).fetchone()
            used = int(row[0]) if row else 0
            if budget is not None and used >= budget:
                db.execute("ROLLBACK")
                raise QuotaExceeded(
                    f"{provider}: daily budget of {budget} calls used up ({day} PT)"
                )
            db.execute(
                "INSERT INTO calls VALUES (?, ?, 1) "
                "ON CONFLICT(provider, day) DO UPDATE SET count = count + 1",
                (provider, day),
            )
            db.execute("COMMIT")
        finally:
            db.close()
