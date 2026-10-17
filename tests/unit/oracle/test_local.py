from dlens_oracle import perturb as P
from dlens_oracle import thresholds as th
from dlens_oracle.build import Warehouse
from dlens_oracle.controls import row_order
from dlens_oracle.gold import Gold

from .conftest import make_toy_gold


def _results(warehouse: Warehouse, gold: Gold) -> dict[str, P.LocalResult]:
    order = row_order(warehouse, seed=1)
    results, dead = P.local_check(warehouse, gold, order, th.ThresholdFile([]))
    assert set(dead) == {f"{m}.{c}" for m in ("orders_users", "first_per_user")
                         for c in warehouse.types(m)}  # fmt: skip
    return {r.column: r for r in results}


def test_local_check_confirms_the_make_toy_gold(warehouse: Warehouse) -> None:
    r = _results(warehouse, make_toy_gold())
    assert all(not x.category_a for x in r.values())
    assert {c.dst for c in r["raw_users.name"].confirmed} == {"orders_users.name"}
    # status decides which rows exist: every target is observed through FILTER alone
    status = r["stg_orders.status"]
    assert {c.dst for c in status.indirect_only} == {"orders_users.order_id", "orders_users.amount",
                                                     "orders_users.name"}  # fmt: skip
    assert all(c.row_count_modes for c in status.indirect_only)


def test_row_preserving_join_needs_the_target_from_the_other_side(warehouse: Warehouse) -> None:
    r = _results(warehouse, make_toy_gold())
    # raw_users.id is the LEFT JOIN's other side: order_id / amount can't change; tagged
    users = {c.dst: c for c in r["raw_users.id"].category_b}
    assert {d: c.tag for d, c in users.items()} == {
        "orders_users.order_id": "row_preserving_join", "orders_users.amount": "row_preserving_join"
    }  # fmt: skip
    # stg_orders.user_id: the targets read stg_orders itself (condition b fails): owner list
    own = {c.dst: c for c in r["stg_orders.user_id"].category_b}
    assert set(own) == {"orders_users.order_id", "orders_users.amount"}
    assert all(c.tag is None and "target reads" in c.note for c in own.values())


def test_missing_gold_edge_is_category_a(warehouse: Warehouse) -> None:
    r = _results(warehouse, make_toy_gold(drop=("raw_users.name", "orders_users.name")))
    a = r["raw_users.name"].category_a
    assert [(c.src, c.dst, c.labels) for c in a] == [("raw_users.name", "orders_users.name", [])]
    assert a[0].modes  # evidence: which modes changed it


def test_order_sensitive_category_a_carries_control_b(warehouse: Warehouse) -> None:
    gold = make_toy_gold(drop=("stg_orders.order_id", "first_per_user.order_id"))
    r = _results(warehouse, gold)
    a = {c.dst: c for c in r["stg_orders.order_id"].category_a}
    assert a["first_per_user.order_id"].order_sensitive == ["stg_orders"]


def _run(**kw: object) -> P.ColumnRun:
    run = P.ColumnRun("stg_orders.status", "VARCHAR", modes=["remap_existing", "shuffle"])
    for k, v in kw.items():
        setattr(run, k, v)
    return run


def test_errors_block_every_tag(warehouse: Warehouse) -> None:
    case = P.Case("raw_users.id", "orders_users.amount", ["JOIN"])
    run = P.ColumnRun("raw_users.id", "INTEGER", modes=["relabel", "shuffle"],
                      errors={"orders_users": {"relabel": "Conversion Error: boom"}})  # fmt: skip
    tag, note = P._tag(case, run, "raw_users", make_toy_gold(), warehouse, {})
    assert tag is None and "errored" in note and "boom" in note


def test_filter_not_crossed_only_with_zero_crossings(warehouse: Warehouse) -> None:
    t = th.Threshold(
        "done", "orders_users", (1,), "status = 'done'", "FILTER", (), ("stg_orders.status",), ""
    )
    case = P.Case("stg_orders.status", "orders_users.amount", ["FILTER"])
    zero = _run(crossings={"done": {"remap_existing": 0, "shuffle": 0}})
    some = _run(crossings={"done": {"remap_existing": 2, "shuffle": 0}})
    by_model = {"orders_users": [t]}
    assert (
        P._tag(case, zero, "stg_orders", make_toy_gold(), warehouse, by_model)[0]
        == "filter_not_crossed"
    )
    tag, note = P._tag(case, some, "stg_orders", make_toy_gold(), warehouse, by_model)
    assert tag is None and "done=2" in note


def test_constant_target(warehouse: Warehouse) -> None:
    warehouse.con.execute("CREATE TABLE base.const_model AS SELECT 1 AS k, 'x' AS src")
    case = P.Case("stg_orders.status", "const_model.src", ["GROUP_BY"])
    assert (
        P._tag(case, _run(), "stg_orders", make_toy_gold(), warehouse, {})[0] == "constant_target"
    )


def test_sort_no_limit_text_rules() -> None:
    plain = "select a, b from t order by a, b"
    assert P.sort_no_limit(plain, "a")
    assert not P.sort_no_limit(plain + " limit 10", "a")
    windowed = "select a, row_number() over (partition by b order by a) as n from t order by a"
    assert not P.sort_no_limit(windowed, "a") and P.sort_no_limit(windowed, "b")
    agg = "select string_agg(code, ',' order by pct desc) as codes from t order by pct"
    assert not P.sort_no_limit(agg, "pct")


def test_spot_check_sample_is_seeded() -> None:
    cases = [P.Case(f"a.c{i}", "b.x", ["JOIN"]) for i in range(30)]
    assert P.spot_check_sample(cases, 1) == P.spot_check_sample(cases, 1)
    assert len(P.spot_check_sample(cases, 1)) == 10
    assert P.spot_check_sample(cases, 1) != P.spot_check_sample(cases, 2)
