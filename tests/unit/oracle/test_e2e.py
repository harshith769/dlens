from dlens_oracle.build import Warehouse
from dlens_oracle.e2e import e2e_check

from .conftest import make_toy_gold


def test_e2e_matches_closure_and_restores(warehouse: Warehouse) -> None:
    gold = make_toy_gold()
    results = {r.column: r for r in e2e_check(warehouse, gold, local_b=set())}
    assert set(results) == {f"{s}.{c}" for s in ("raw_orders", "raw_users")
                            for c in warehouse.types(s)}  # fmt: skip
    assert all(not r.category_a and not r.errors for r in results.values())
    status = results["raw_orders.status"]
    # stg_orders.status -> orders_users.* is FILTER only: reachable only with indirect edges
    assert set(status.indirect_only) == {"orders_users.order_id", "orders_users.amount",
                                         "orders_users.name"}  # fmt: skip
    assert "stg_orders.status" in status.closure_direct
    for model in warehouse.corpus.models:  # every table restored after the run
        assert warehouse.table_fingerprint(model) == warehouse.table_fingerprint(model, "base")


def test_e2e_category_a_and_explained_unobserved(warehouse: Warehouse) -> None:
    gold = make_toy_gold(drop=("raw_users.name", "orders_users.name"))
    results = {r.column: r for r in e2e_check(warehouse, gold, local_b=set())}
    assert results["raw_users.name"].category_a == ["orders_users.name"]
    # raw_users.id reaches order_id / amount only through JOIN pairs the local check didn't see
    b = {("raw_users.id", "orders_users.order_id"), ("raw_users.id", "orders_users.amount")}
    users = {r.column: r for r in e2e_check(warehouse, make_toy_gold(), local_b=b)}["raw_users.id"]
    assert users.unobserved_explained == ["orders_users.amount", "orders_users.order_id"]
    assert users.unobserved_unexplained == []
    unexplained = {r.column: r for r in e2e_check(warehouse, make_toy_gold(), local_b=set())}
    assert unexplained["raw_users.id"].unobserved_unexplained == [
        "orders_users.amount", "orders_users.order_id"
    ]  # fmt: skip
