from pathlib import Path

import pytest
from sqlglot import exp
from sqlglot.lineage import lineage

from dlens.ingest import IngestResult
from dlens.ingest.artifacts import Catalog, Manifest
from dlens.lineage import (
    Confidence,
    EdgeKind,
    ParseQuality,
    column_id,
    compare,
    extract_lineage,
    lineage_for_sql,
    short_id,
)
from dlens.lineage.engine import _model_edges
from dlens.lineage.models import Edge
from dlens.lineage.provenance import locate, select_items

SCHEMA = {
    "db": {
        "main": {
            "orders": {"id": "int", "user_id": "int", "amt": "int", "order_date": "date"},
            "customers": {"id": "int", "name": "varchar"},
            "refunds": {"id": "int", "amt": "int"},
            "unknown_node": {"id": "int"},
        }
    }
}
RELATIONS = {
    "db.main.orders": "seed.p.orders",
    "db.main.customers": "seed.p.customers",
    "db.main.refunds": "seed.p.refunds",
}


def _ingest(models: dict[str, str] | None = None) -> IngestResult:
    nodes = {
        f"model.p.{name}": {
            "unique_id": f"model.p.{name}",
            "resource_type": "model",
            "name": name,
            "original_file_path": f"models/{name}.sql",
            "compiled_code": sql,
            "depends_on": {"nodes": ["seed.p.orders"]},
        }
        for name, sql in (models or {}).items()
    }
    return IngestResult(
        manifest=Manifest.model_validate({"nodes": nodes, "exposures": {}}),
        catalog=Catalog(tables=[]),
        schema=SCHEMA,
        relation_map=RELATIONS,
        unmapped=[],
    )


def _edges(sql: str) -> dict[tuple[str, str], Edge]:
    from dlens.ingest.artifacts import Node

    model = Node(unique_id="model.p.m", resource_type="model", name="m")
    raw = lineage_for_sql(sql, _ingest())
    return {
        (short_id(e.from_column), short_id(e.to_column)): e
        for e in _model_edges(model, raw, None, "duckdb")
    }


def _kinds(sql: str) -> dict[tuple[str, str], EdgeKind]:
    return {k: e.kind for k, e in _edges(sql).items()}


def test_identity_rename_transformation() -> None:
    assert _kinds("select id, user_id as customer_id, amt * 2 as dbl from db.main.orders") == {
        ("orders.id", "m.id"): EdgeKind.IDENTITY,
        ("orders.user_id", "m.customer_id"): EdgeKind.RENAME,
        ("orders.amt", "m.dbl"): EdgeKind.TRANSFORMATION,
    }


def test_case_condition_columns_are_direct_edges() -> None:
    kinds = _kinds("select case when amt > id then 1 else 0 end as flag from db.main.orders")
    assert kinds == {
        ("orders.amt", "m.flag"): EdgeKind.TRANSFORMATION,
        ("orders.id", "m.flag"): EdgeKind.TRANSFORMATION,
    }


def test_aggregate_in_cte_is_strongest_kind() -> None:
    sql = """
        with agg as (select user_id, sum(amt) as total from db.main.orders group by user_id)
        select c.id, coalesce(agg.total, 0) as total
        from db.main.customers as c left join agg on c.id = agg.user_id
    """
    kinds = _kinds(sql)
    assert kinds[("orders.amt", "m.total")] == EdgeKind.AGGREGATION
    assert ("orders.user_id", "m.total") not in kinds  # join / group key only


def test_rename_inside_cte_then_passthrough_is_rename() -> None:
    sql = "with x as (select amt as amount from db.main.orders) select amount from x"
    assert _kinds(sql) == {("orders.amt", "m.amount"): EdgeKind.RENAME}


def test_window_keys_are_deferred_not_edges() -> None:
    sql = (
        "select lag(order_date) over (partition by user_id order by order_date, id) as prev "
        "from db.main.orders"
    )
    raw = lineage_for_sql(sql, _ingest())
    assert _kinds(sql) == {("orders.order_date", "m.prev"): EdgeKind.TRANSFORMATION}
    assert sorted(short_id(up) for up, _ in raw.deferred) == ["orders.id", "orders.user_id"]


def test_lineage_trees_share_the_qualified_scope_ast() -> None:
    """Direct and indirect edges read one qualified AST: every projection on a lineage tree
    belongs to a SELECT of the shared scope tree (identity, not a copy)."""
    sql = (
        "with x as (select user_id, sum(amt) as total from db.main.orders group by user_id) "
        "select c.name, x.total from db.main.customers as c join x on c.id = x.user_id"
    )
    raw = lineage_for_sql(sql, _ingest())
    assert raw.scope is not None
    selects = {id(s.expression) for s in raw.scope.traverse()}
    trees = lineage(None, raw.scope.expression, scope=raw.scope, schema=SCHEMA, trim_selects=False)
    assert isinstance(trees, dict)
    for root in trees.values():
        for node in root.walk():
            if not isinstance(node.expression, exp.Table):
                assert id(node.expression.parent_select) in selects


def test_aggregate_filter_and_order_keys_are_not_direct_inputs() -> None:
    """ADR 0020: an aggregate's FILTER (WHERE) column is CONDITIONAL and an ORDER BY inside an
    aggregate is SORT; neither is a direct input. The CASE form of the same logic is direct."""
    sql = (
        "select user_id, count(id) filter (where amt > 0) as paid, "
        "sum(case when amt > 0 then 1 else 0 end) as paid_case, "
        "string_agg(cast(id as varchar), ',' order by order_date) as ids "
        "from db.main.orders group by user_id"
    )
    raw = lineage_for_sql(sql, _ingest())
    assert _kinds(sql) == {
        ("orders.user_id", "m.user_id"): EdgeKind.IDENTITY,
        ("orders.id", "m.paid"): EdgeKind.AGGREGATION,
        ("orders.amt", "m.paid_case"): EdgeKind.AGGREGATION,
        ("orders.id", "m.ids"): EdgeKind.AGGREGATION,
    }
    assert raw.deferred == []  # only window keys are deferred


def test_a_key_column_also_read_as_a_value_stays_direct() -> None:
    sql = "select string_agg(cast(amt as varchar), ',' order by amt) as s from db.main.orders"
    assert _kinds(sql) == {("orders.amt", "m.s"): EdgeKind.AGGREGATION}


def test_aggregate_over_window_is_transformation() -> None:
    kinds = _kinds("select sum(amt) over (partition by user_id) as running from db.main.orders")
    assert kinds == {("orders.amt", "m.running"): EdgeKind.TRANSFORMATION}


def test_union_all_one_edge_per_branch_with_own_kind() -> None:
    sql = (
        "select amt as value from db.main.orders union all select -1 * amt as value "
        "from db.main.refunds"
    )
    assert _kinds(sql) == {
        ("orders.amt", "m.value"): EdgeKind.RENAME,
        ("refunds.amt", "m.value"): EdgeKind.TRANSFORMATION,
    }


def test_select_star_expands_to_identity_edges() -> None:
    kinds = _kinds("select * from db.main.customers")
    assert kinds == {
        ("customers.id", "m.id"): EdgeKind.IDENTITY,
        ("customers.name", "m.name"): EdgeKind.IDENTITY,
    }


def test_ambiguous_column_gets_low_confidence_edge_per_candidate() -> None:
    edges = _edges("select amt from db.main.orders, db.main.refunds")
    assert set(edges) == {("orders.amt", "m.amt"), ("refunds.amt", "m.amt")}
    assert all(e.confidence == Confidence.LOW for e in edges.values())


def test_unmapped_table_is_a_gap() -> None:
    raw = lineage_for_sql("select id from db.main.unknown_node", _ingest())
    assert raw.edges == []
    assert raw.gaps and "not a dbt node" in raw.gaps[0]


def test_extract_lineage_quality_and_depends_on(tmp_path: Path) -> None:
    (tmp_path / "models").mkdir()
    (tmp_path / "models" / "good.sql").write_text("select\n    id as order_id\nfrom x\n")
    ingest = _ingest(
        {
            "good": "select id as order_id from db.main.orders",
            "partial": "select o.id, u.id as uid from db.main.orders o, db.main.unknown_node u",
            "broken": "select from where (",
        }
    )
    result = extract_lineage(ingest, tmp_path)
    report = result.parse_report
    assert report["model.p.good"].quality == ParseQuality.FULL
    assert report["model.p.partial"].quality == ParseQuality.TABLE_ONLY
    assert report["model.p.broken"].quality == ParseQuality.FAILED
    assert report["model.p.broken"].reason
    assert ("model.p.broken", "seed.p.orders") in result.depends_on  # never dropped
    good = [e for e in result.edges if e.to_column == "model.p.good.order_id"]
    assert len(good) == 1
    assert good[0].lines == (2, 2) and not good[0].model_level_citation
    assert good[0].file == "models/good.sql"
    partial_targets = {e.to_column for e in result.edges if "partial" in e.to_column}
    assert partial_targets == {"model.p.partial.id"}


def test_column_id_and_short_id() -> None:
    assert column_id("model.Shop.Stg_Orders", "Order_ID") == "model.shop.stg_orders.order_id"
    assert short_id("source.shop.raw.orders.id") == "orders.id"


SOURCE = """with agg as (
    select order_id, sum(amt) as total  -- per order
    from {{ ref('orders') }}
    group by order_id
)
select
    o.order_id,
    case o.status
        when 'a, b' then 'x'
        else 'y'
    end as status_group,
    coalesce(agg.total, 0) as total,
    {{ dynamic_col }}_amount
from {{ ref('orders') }} as o
left join agg on o.order_id = agg.order_id
"""


def test_select_items_parses_jinja_strings_and_nesting() -> None:
    names = [it.name for it in select_items(SOURCE)]
    assert names == ["order_id", "total", "order_id", "status_group", "total", None]


@pytest.mark.parametrize(
    ("column", "lines"),
    [("order_id", (7, 7)), ("status_group", (8, 11)), ("total", (12, 12))],
)
def test_locate_uses_last_select(column: str, lines: tuple[int, int]) -> None:
    cite = locate(SOURCE, column)
    assert cite.lines == lines and not cite.model_level


def test_locate_union_branch_and_star_and_fallback() -> None:
    union = "select a as x from t\nunion all\nselect b as x from u\n"
    assert locate(union, "x", branch=0).lines == (1, 1)
    assert locate(union, "x", branch=1).lines == (3, 3)
    assert locate("select\n    *\nfrom {{ ref('t') }}\n", "anything").lines == (2, 2)
    fallback = locate(SOURCE, "credit_card_amount")
    assert fallback.model_level and fallback.lines == (1, 15)


def _edge(src: str, dst: str, kind: EdgeKind) -> Edge:
    return Edge(
        from_column=f"model.p.{src}", to_column=f"model.p.{dst}", kind=kind,
        expression="", file="f.sql", lines=(1, 1),
    )  # fmt: skip


def test_compare_metrics() -> None:
    engine = [
        _edge("a.x", "b.x", EdgeKind.IDENTITY),
        _edge("a.y", "b.z", EdgeKind.TRANSFORMATION),
        _edge("a.q", "b.q", EdgeKind.IDENTITY),
    ]
    gold = [
        {"from": "a.x", "to": "b.x", "kind": "IDENTITY"},
        {"from": "a.y", "to": "b.z", "kind": "RENAME"},
        {"from": "a.w", "to": "b.w", "kind": "IDENTITY"},
        {"from": "a.v", "to": "b.v", "kind": "IDENTITY"},
    ]
    r = compare(engine, gold)
    assert r.matched == 2
    assert r.precision == pytest.approx(2 / 3) and r.recall == pytest.approx(0.5)
    assert r.f1 == pytest.approx(2 * (2 / 3) * 0.5 / (2 / 3 + 0.5))
    assert r.kind_accuracy == 0.5
    assert r.missing == [("a.v", "b.v", "IDENTITY"), ("a.w", "b.w", "IDENTITY")]
    assert r.extra == [("a.q", "b.q", "IDENTITY")]
    assert r.kind_mismatches == [("a.y", "b.z", "RENAME", "TRANSFORMATION")]


def _clauses(sql: str) -> dict[tuple[str, str], str]:
    """(type, key) -> clause text of the indirect candidates (before suppression)."""
    return {(str(r.kind), r.key): r.clause for r in lineage_for_sql(sql, _ingest()).indirect}


@pytest.mark.parametrize(
    ("sql", "kind", "key", "clause"),
    [
        (
            "select o.id from db.main.orders as o\n"
            "join db.main.customers as c\n    on o.user_id = c.id\nwhere o.amt > 0",
            "JOIN",
            "o.user_id",
            "on o.user_id = c.id",
        ),
        (
            "select id from db.main.orders where not (amt > 0) and user_id is not null",
            "FILTER",
            "orders.user_id",
            "where not (amt > 0) and user_id is not null",
        ),
        (
            "select lag(amt) over (\n  partition by user_id\n  order by order_date desc\n) as p "
            "from db.main.orders",
            "WINDOW",
            "orders.order_date",
            "over ( partition by user_id order by order_date desc )",
        ),
        (
            "select count(id) filter (where amt > 0) as n from db.main.orders",
            "CONDITIONAL",
            "orders.amt",
            "filter (where amt > 0)",
        ),
        (
            "select string_agg(cast(id as varchar), ',' order by order_date desc) as s "
            "from db.main.orders",
            "SORT",
            "orders.order_date",
            "order by order_date desc",
        ),
        (
            "select c.id from db.main.customers as c where exists "
            "(select 1 from db.main.orders as o where o.user_id = c.id)",
            "FILTER",
            "o.user_id",
            "where exists (select 1 from db.main.orders as o where o.user_id = c.id)",
        ),
    ],
)
def test_indirect_clause_text_is_verbatim_from_the_compiled_sql(
    sql: str, kind: str, key: str, clause: str
) -> None:
    assert _clauses(sql)[(kind, key)] == clause


def test_clause_text_falls_back_to_qualified_sql_when_tokens_point_elsewhere() -> None:
    """GROUP BY 1 is expanded by qualify with copies of the projection's tokens: the text is
    the qualified clause, not a wrong slice of the SELECT list."""
    sql = (
        "with x as (select id from db.main.orders group by id) "
        "select user_id from db.main.orders group by 1"
    )
    assert _clauses(sql)[("GROUP_BY", "orders.user_id")] == "GROUP BY orders.user_id"


def test_unqualified_ambiguous_key_is_low_confidence_to_each_candidate() -> None:
    sql = (
        "select o.amt from db.main.orders as o "
        "join db.main.customers as c on o.user_id = c.id where id > 0"
    )
    raw = lineage_for_sql(sql, _ingest())
    lows = {(short_id(r.upstream), str(r.confidence)) for r in raw.indirect if r.kind == "FILTER"}
    assert lows == {("orders.id", "low"), ("customers.id", "low")}  # `id` is in both tables


def test_compare_indirect_scores_triples_per_type_and_model() -> None:
    from dlens.lineage import IndirectEdge, IndirectKind, compare_indirect

    def ind(f: str, t: str, k: IndirectKind) -> IndirectEdge:
        return IndirectEdge(
            from_column=f"model.p.{f}", to_column=f"model.p.{t}", kind=k, key="k",
            expression="on k", file="m.sql", lines=(1, 1),
        )  # fmt: skip

    engine = [
        ind("a.k", "m.x", IndirectKind.JOIN),
        ind("a.k", "m.x", IndirectKind.GROUP_BY),  # same pair, second type
        ind("a.k", "n.y", IndirectKind.FILTER),  # extra
    ]
    gold = [("a.k", "m.x", "JOIN"), ("a.k", "m.x", "GROUP_BY"), ("b.k", "m.x", "JOIN")]
    r = compare_indirect(engine, gold)
    assert (r.overall.matched, r.overall.engine, r.overall.gold) == (2, 3, 3)
    assert r.overall.precision == pytest.approx(2 / 3) and r.overall.recall == pytest.approx(2 / 3)
    assert r.by_type["JOIN"].recall == 0.5 and r.by_type["GROUP_BY"].f1 == 1.0
    assert r.by_type["FILTER"].precision == 0.0
    assert r.by_model["m"].precision == 1.0 and r.by_model["n"].matched == 0
    assert r.missing == [("b.k", "m.x", "JOIN")] and r.extra == [("a.k", "n.y", "FILTER")]
