from datetime import UTC, datetime

import pytest

from dlens.agent.llm.config import cache_path, quota_path
from dlens.agent.llm.quota import PACIFIC, QuotaCounter, default_budgets
from dlens.agent.llm.types import QuotaExceeded

from .conftest import FakeClock


def counter(tmp_path, clock, budget=400):
    return QuotaCounter(tmp_path / "q.sqlite", {"gemini": budget, "ollama": None}, clock.dt)


def test_blocks_exactly_at_budget(tmp_path, clock):
    q = counter(tmp_path, clock, budget=400)
    for _ in range(400):
        q.reserve("gemini")
    assert (q.used("gemini"), q.remaining("gemini")) == (400, 0)
    with pytest.raises(QuotaExceeded):
        q.reserve("gemini")
    assert q.used("gemini") == 400  # the refused call was not counted


def test_resets_at_pacific_midnight(tmp_path):
    clock = FakeClock(datetime(2026, 10, 5, 23, 59, 59, tzinfo=PACIFIC))
    q = counter(tmp_path, clock, budget=1)
    q.reserve("gemini")
    with pytest.raises(QuotaExceeded):
        q.reserve("gemini")
    clock.advance(1)  # 00:00:00 PT
    assert q.used("gemini") == 0
    q.reserve("gemini")


def test_reset_follows_pacific_not_utc(tmp_path):
    # 2026-10-06 03:00 UTC is still 10-05 20:00 PDT: the same quota day as 10-05 12:00 PDT.
    clock = FakeClock(datetime(2026, 10, 5, 12, 0, tzinfo=PACIFIC))
    q = counter(tmp_path, clock, budget=1)
    q.reserve("gemini")
    clock.now = datetime(2026, 10, 6, 3, 0, tzinfo=UTC)
    assert q.used("gemini") == 1
    clock.now = datetime(2026, 10, 6, 7, 0, tzinfo=UTC)  # 00:00 PDT on 10-06
    assert q.used("gemini") == 0


def test_dst_fall_back_day_is_one_quota_day(tmp_path):
    # 2026-11-01 has 25 hours in Los Angeles; 01:30 occurs twice, both on the same date.
    first = datetime(2026, 11, 1, 1, 30, tzinfo=PACIFIC, fold=0)
    clock = FakeClock(first)
    q = counter(tmp_path, clock, budget=1)
    q.reserve("gemini")
    clock.now = datetime(2026, 11, 1, 1, 30, tzinfo=PACIFIC, fold=1)
    assert q.used("gemini") == 1
    clock.now = datetime(2026, 11, 2, 0, 0, tzinfo=PACIFIC)
    assert q.used("gemini") == 0


def test_providers_isolated_and_unbudgeted_unlimited(tmp_path, clock):
    q = counter(tmp_path, clock, budget=1)
    q.reserve("gemini")
    for _ in range(1000):
        q.reserve("ollama")
    assert q.remaining("ollama") is None
    assert q.used("ollama") == 1000


def test_persists_across_instances(tmp_path, clock):
    counter(tmp_path, clock).reserve("gemini")
    assert counter(tmp_path, clock).used("gemini") == 1


def test_budget_from_env():
    assert default_budgets({})["gemini"] == 400
    assert default_budgets({"GEMINI_DAILY_BUDGET": "380"})["gemini"] == 380


def test_paths_are_separate_and_overridable(tmp_path):
    env = {"XDG_CACHE_HOME": str(tmp_path / "xc"), "XDG_STATE_HOME": str(tmp_path / "xs")}
    assert cache_path(env) == tmp_path / "xc" / "dlens" / "llm.sqlite"
    assert quota_path(env) == tmp_path / "xs" / "dlens" / "quota.sqlite"
    env |= {"DLENS_CACHE_DIR": str(tmp_path / "cc"), "DLENS_STATE_DIR": str(tmp_path / "ss")}
    assert cache_path(env) == tmp_path / "cc" / "llm.sqlite"
    assert quota_path(env) == tmp_path / "ss" / "quota.sqlite"
    assert cache_path(env).parent != quota_path(env).parent
