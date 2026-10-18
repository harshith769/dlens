"""scripts/question_pools.py: dev/test column pools are deterministic, stratified and complete."""

import importlib.util
from collections import Counter
from pathlib import Path

import yaml

ROOT = Path(__file__).parents[2]
_spec = importlib.util.spec_from_file_location(
    "question_pools", ROOT / "scripts" / "question_pools.py"
)
assert _spec and _spec.loader
qp = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(qp)

SPEC = yaml.safe_load(qp.SPEC.read_text())
TRAPS = yaml.safe_load(qp.TRAPS.read_text())
POOLS = qp.build(SPEC, TRAPS)
COLS = POOLS["columns"]


def test_file_on_disk_is_fresh_and_build_is_deterministic():
    assert qp.render(qp.build(SPEC, TRAPS)) == qp.render(POOLS)
    assert qp.OUT.read_text() == qp.render(POOLS), "run scripts/question_pools.py"


def test_every_spec_column_has_exactly_one_split():
    v = qp.gs.build_view(SPEC)
    assert set(COLS) == v.seed_columns | v.model_columns
    assert {x["split"] for x in COLS.values()} == {"dev", "test"}


def test_v02_targets_are_forced_into_dev():
    existing = [c for c in qp.V02_TARGETS if c in COLS]
    # 20 questions, 19 distinct targets (dev-11 and dev-17 share fct_orders.revenue_finance);
    # dev-19's target, stg_orders.ship_date, does not exist.
    assert len(existing) == 18
    assert all(COLS[c]["split"] == "dev" for c in existing)


def test_quota_per_stratum():
    for s in POOLS["strata"]:
        dev = sum(1 for x in COLS.values() if x["stratum"] == s["stratum"] and x["split"] == "dev")
        assert dev == s["dev"]
        if s["n"] >= 2:
            assert dev >= max(s["forced"], 1) and dev < s["n"] or s["forced"] == s["n"]


def test_small_traps_split_between_dev_and_test():
    for trap in ("stale_doc", "fan_in_aggregate", "join_key_only", "rename_chain"):
        splits = Counter(x["split"] for x in COLS.values() if x["stratum"] == f"any|{trap}")
        assert splits["dev"] >= 1 and splits["test"] >= 1, trap
    stale = Counter(x["split"] for x in COLS.values() if x["stratum"] == "any|stale_doc")
    assert stale == {"dev": 1, "test": 1}


def test_dev_pool_covers_the_count_table():
    assert qp.coverage(POOLS, SPEC) == []


def test_share_is_about_thirty_percent():
    dev = sum(1 for x in COLS.values() if x["split"] == "dev")
    assert 0.27 <= dev / len(COLS) <= 0.33


def test_pools_hold_no_question_text():
    assert set(POOLS) == {"salt", "share", "strata", "columns"}
    assert all(set(x) == {"split", "stratum"} for x in COLS.values())
