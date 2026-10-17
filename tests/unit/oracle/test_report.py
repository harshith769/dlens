import json
import time

from dlens_oracle import thresholds as th
from dlens_oracle.build import Corpus, Warehouse
from dlens_oracle.report import render, undecided
from dlens_oracle.run import _run, comparable

from .conftest import make_toy_gold


def _doc(toy: Corpus, warehouse: Warehouse) -> dict:
    doc = _run(toy, warehouse, make_toy_gold(), th.ThresholdFile([]), 1, None, None,
               {"dbt_compile": 0.0}, time.perf_counter())  # fmt: skip
    return json.loads(json.dumps(doc))  # what the CLI writes and reads back


def test_document_is_json_and_deterministic(toy: Corpus, warehouse: Warehouse) -> None:
    a = _doc(toy, warehouse)
    assert comparable(a) == comparable(_doc(toy, warehouse))
    assert a["local"]["summary"]["category_a"] == 0
    assert a["controls"]["order_sensitive"] == {"first_per_user.order_id": ["stg_orders"]}


def test_undecided_and_owner_decisions(toy: Corpus, warehouse: Warehouse) -> None:
    doc = _doc(toy, warehouse)
    none = {"category_a": [], "category_b": []}
    pending = undecided(doc, none)
    assert pending["category_a"] == []
    src = "stg_orders.user_id"
    assert sorted(pending["category_b"]) == [
        (src, "orders_users.amount"),
        (src, "orders_users.order_id"),
    ]
    assert "**pending**" in render(doc, none)
    decided = {
        "category_a": [],
        "category_b": [
            {"from": f, "to": t, "check": "local", "reason": "preserved side", "decision": "accept",
             "decided": "2026-10-17"} for f, t in pending["category_b"]
        ],
    }  # fmt: skip
    assert undecided(doc, decided) == {"category_a": [], "category_b": []}
    report = render(doc, decided)
    assert "**pending**" not in report and "Undecided: 0 category A, 0 category B." in report
