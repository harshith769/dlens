from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime
from pathlib import Path
from typing import Any

import pytest

from dlens.agent.llm.base import LLMClient, Provider
from dlens.agent.llm.cache import ResponseCache
from dlens.agent.llm.quota import PACIFIC, QuotaCounter
from dlens.agent.llm.ratelimit import RateLimiter
from dlens.agent.llm.types import LLMResponse, Message, ToolSpec, Usage


class FakeProvider(Provider):
    name = "gemini"
    model = "fake-1"

    def __init__(self, name: str = "gemini") -> None:
        self.name = name
        self.calls = 0

    @property
    def params(self) -> dict[str, Any]:
        return {"temperature": 0}

    def send(
        self,
        messages: Sequence[Message],
        tools: Sequence[ToolSpec] | None,
        response_schema: dict[str, Any] | None = None,
    ) -> LLMResponse:
        self.calls += 1
        self.last_schema = response_schema
        return LLMResponse(text=f"reply {self.calls}", usage=Usage(input_tokens=5, output_tokens=2))


class FakeClock:
    """Shared fake time: seconds for the limiter, a Pacific datetime for the quota counter."""

    def __init__(self, start: datetime | None = None) -> None:
        self.now = start or datetime(2026, 10, 5, 12, 0, tzinfo=PACIFIC)
        self.slept: list[float] = []

    def dt(self) -> datetime:
        return self.now

    def seconds(self) -> float:
        return self.now.timestamp()

    def sleep(self, s: float) -> None:
        self.slept.append(s)
        self.advance(s)

    def advance(self, s: float) -> None:
        from datetime import timedelta

        self.now = self.now + timedelta(seconds=s)


@pytest.fixture
def clock() -> FakeClock:
    return FakeClock()


@pytest.fixture
def make(tmp_path: Path, clock: FakeClock):
    def _make(budget: int | None = 400, rpm: int | None = None, name: str = "gemini", **kw: Any):
        provider = FakeProvider(name)
        client = LLMClient(
            provider,
            ResponseCache(tmp_path / "cache" / "llm.sqlite"),
            QuotaCounter(tmp_path / "state" / "quota.sqlite", {name: budget}, clock.dt),
            RateLimiter(rpm, clock.seconds, clock.sleep),
            **kw,
        )
        return client, provider

    return _make


def user(text: str) -> list[Message]:
    return [Message(role="user", content=text)]
