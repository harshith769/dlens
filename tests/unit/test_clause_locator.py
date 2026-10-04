"""Clause-level citations for indirect edges (S04). Expectations are written by hand from the
source SQL: the lines of the clause that holds the key, in the model's SOURCE file (the same file
and numbering as direct edges). Compiled SQL is the source with ``ref`` rendered, unless a case
gives it explicitly (Jinja loops and macros change the line count or the text)."""

import re
from pathlib import Path

import pytest

from dlens.ingest import IngestResult
from dlens.ingest.artifacts import Catalog, Manifest
from dlens.lineage import Edge, IndirectEdge, ModelParse, extract_lineage, short_id

SCHEMA = {
    "db": {
        "main": {
            "orders": {"id": "int", "user_id": "int", "amt": "int", "order_date": "date"},
            "customers": {"id": "int", "name": "varchar"},
            "refunds": {"id": "int", "amt": "int"},
        }
    }
}
RELATIONS = {f"db.main.{t}": f"seed.p.{t}" for t in ("orders", "customers", "refunds")}
MODEL = "model.p.m"


def _compile(source: str) -> str:
    return re.sub(r"\{\{ ref\('(\w+)'\) \}\}", r"db.main.\1", source)


def _run(
    tmp_path: Path, source: str, compiled: str | None = None
) -> tuple[dict[tuple[str, str, str], IndirectEdge], ModelParse, list[Edge]]:
    (tmp_path / "models").mkdir(exist_ok=True)
    (tmp_path / "models" / "m.sql").write_text(source)
    node = {
        "unique_id": MODEL,
        "resource_type": "model",
        "name": "m",
        "original_file_path": "models/m.sql",
        "compiled_code": compiled if compiled is not None else _compile(source),
        "depends_on": {"nodes": []},
    }
    ingest = IngestResult(
        manifest=Manifest.model_validate({"nodes": {MODEL: node}, "exposures": {}}),
        catalog=Catalog(tables=[]),
        schema=SCHEMA,
        relation_map=RELATIONS,
        unmapped=[],
    )
    result = extract_lineage(ingest, tmp_path)
    indirect = {
        (short_id(e.from_column), short_id(e.to_column), str(e.kind)): e for e in result.indirect
    }
    return indirect, result.parse_report[MODEL], result.edges


# (id, source, compiled or None, {(from, to, type): (lines, key)})
CASES = [
    (
        "where_in_cte_multiline",
        """with recent as (
    select id, user_id, amt
    from {{ ref('orders') }}
    where order_date
        > date '2024-01-01'
)
select id, user_id, amt from recent
""",
        None,
        {("orders.order_date", "m.amt", "FILTER"): ((4, 5), "orders.order_date")},
    ),
    (
        "join_on",
        """select
    o.id,
    c.name
from {{ ref('orders') }} as o
left join {{ ref('customers') }} as c
    on o.user_id = c.id
""",
        None,
        {
            ("orders.user_id", "m.name", "JOIN"): ((6, 6), "o.user_id"),
            ("customers.id", "m.id", "JOIN"): ((6, 6), "c.id"),
        },
    ),
    (
        "join_using",
        """select
    o.user_id,
    r.amt
from {{ ref('orders') }} as o
join {{ ref('refunds') }} as r
    using (id)
""",
        None,
        {
            ("orders.id", "m.amt", "JOIN"): ((6, 6), "o.id"),
            ("refunds.id", "m.user_id", "JOIN"): ((6, 6), "r.id"),
        },
    ),
    (
        "group_by_and_having",
        """select
    user_id,
    sum(amt) as total
from {{ ref('orders') }}
group by
    user_id
having
    max(order_date) > date '2024-01-01'
""",
        None,
        {
            ("orders.user_id", "m.total", "GROUP_BY"): ((5, 6), "orders.user_id"),
            ("orders.order_date", "m.user_id", "FILTER"): ((7, 8), "orders.order_date"),
            ("orders.order_date", "m.total", "FILTER"): ((7, 8), "orders.order_date"),
        },
    ),
    (
        "qualify",
        """select id, user_id
from {{ ref('orders') }}
qualify row_number() over (
    partition by user_id order by order_date desc
) = 1
""",
        None,
        {
            ("orders.order_date", "m.id", "FILTER"): ((3, 5), "orders.order_date"),
            ("orders.user_id", "m.id", "FILTER"): ((3, 5), "orders.user_id"),
        },
    ),
    (
        "order_by",
        """select id
from {{ ref('orders') }}
order by
    amt desc
limit 5
""",
        None,
        {("orders.amt", "m.id", "SORT"): ((3, 4), "orders.amt")},
    ),
    (
        "over_window",
        """select
    id,
    sum(amt) over (
        partition by user_id
        order by order_date
    ) as running
from {{ ref('orders') }}
""",
        None,
        {
            ("orders.user_id", "m.running", "WINDOW"): ((3, 6), "orders.user_id"),
            ("orders.order_date", "m.running", "WINDOW"): ((3, 6), "orders.order_date"),
        },
    ),
    (
        "aggregate_filter_where",
        """select
    user_id,
    count(id)
        filter (where amt > 100) as big
from {{ ref('orders') }}
group by user_id
""",
        None,
        {
            ("orders.amt", "m.big", "CONDITIONAL"): ((4, 4), "orders.amt"),
            ("orders.user_id", "m.big", "GROUP_BY"): ((6, 6), "orders.user_id"),
        },
    ),
    (
        "aggregate_order_by",
        """select
    user_id,
    string_agg(cast(id as varchar), ','
        order by order_date) as ids
from {{ ref('orders') }}
group by user_id
""",
        None,
        {("orders.order_date", "m.ids", "SORT"): ((4, 4), "orders.order_date")},
    ),
    (
        "positional_group_and_order",
        """select
    user_id,
    sum(amt) as total
from {{ ref('orders') }}
group by 1
order by 2 desc
""",
        None,
        {
            ("orders.user_id", "m.total", "GROUP_BY"): ((5, 5), "1"),
            ("orders.amt", "m.user_id", "SORT"): ((6, 6), "2"),
        },
    ),
    (
        "group_by_all",
        """select
    user_id,
    sum(amt) as total
from {{ ref('orders') }}
group by all
""",
        None,
        {("orders.user_id", "m.total", "GROUP_BY"): ((5, 5), "ALL")},
    ),
    (
        "order_by_alias_differs_from_source",
        """select
    user_id,
    amt as lv
from {{ ref('orders') }}
order by
    lv desc
""",
        None,
        {("orders.amt", "m.user_id", "SORT"): ((5, 6), "lv")},
    ),
    (
        "join_on_cte_column_renamed_from_source",
        """with spend as (
    select user_id as cust_id, sum(amt) as spent
    from {{ ref('orders') }}
    group by user_id
)
select
    c.name,
    s.spent
from {{ ref('customers') }} as c
join spend as s
    on c.id = s.cust_id
""",
        None,
        {
            ("orders.user_id", "m.name", "JOIN"): ((11, 11), "s.cust_id"),
            ("orders.user_id", "m.spent", "JOIN"): ((11, 11), "s.cust_id"),
            ("orders.user_id", "m.spent", "GROUP_BY"): ((4, 4), "orders.user_id"),
            ("customers.id", "m.spent", "JOIN"): ((11, 11), "c.id"),
        },
    ),
    (
        "jinja_loop_shifts_lines",
        """{% set cols = ['a', 'b'] %}
select
    id,
    {% for c in cols -%}
    amt as amt_{{ c }},
    {% endfor -%}
    user_id
from {{ ref('orders') }}
where user_id
    > 0
""",
        """
select
    id,
    amt as amt_a,
    amt as amt_b,
    user_id
from db.main.orders
where user_id
    > 0
""",
        {
            ("orders.user_id", "m.id", "FILTER"): ((9, 10), "orders.user_id"),
            ("orders.user_id", "m.amt_b", "FILTER"): ((9, 10), "orders.user_id"),
        },
    ),
]


def _word(token: str, chunk: str) -> bool:
    return re.search(rf"(?<!\w){re.escape(token)}(?!\w)", chunk, re.IGNORECASE) is not None


def key_is_cited(key: str, chunk: str) -> bool:
    """The clause as written holds the key: its column name, a GROUP BY / ORDER BY position, or
    ``ALL`` of GROUP BY ALL."""
    return _word(key.replace('"', "").split(".")[-1], chunk)


@pytest.mark.parametrize(
    ("source", "compiled", "expected"), [c[1:] for c in CASES], ids=[c[0] for c in CASES]
)
def test_indirect_edges_cite_their_clause_lines(
    tmp_path: Path,
    source: str,
    compiled: str | None,
    expected: dict[tuple[str, str, str], tuple[tuple[int, int], str]],
) -> None:
    indirect, parse, _ = _run(tmp_path, source, compiled)
    got = {k: (indirect[k].lines, indirect[k].key) for k in expected if k in indirect}
    assert got == expected
    lines = source.splitlines()
    for e in indirect.values():  # every indirect edge of the model, not only the listed ones
        assert not e.model_level_citation, e
        assert e.file == "models/m.sql"
        chunk = "\n".join(lines[e.lines[0] - 1 : e.lines[1]])
        assert key_is_cited(e.key, chunk), (e.key, chunk)
    assert parse.citation_gaps == []


def test_a_clause_only_a_macro_writes_falls_back_to_model_level_with_a_reason(
    tmp_path: Path,
) -> None:
    source = "select id\nfrom {{ ref('orders') }}\n{{ only_big_orders() }}\n"
    compiled = "select id\nfrom db.main.orders\nwhere amt > 100\n"
    indirect, parse, _ = _run(tmp_path, source, compiled)
    e = indirect[("orders.amt", "m.id", "FILTER")]
    assert e.model_level_citation and e.lines == (1, 3)
    assert len(parse.citation_gaps) == 1
    assert parse.citation_gaps[0].startswith("FILTER where amt > 100: ")


def test_direct_and_indirect_citations_share_file_and_line_numbering(tmp_path: Path) -> None:
    source = dict((c[0], c[1]) for c in CASES)["join_on_cte_column_renamed_from_source"]
    indirect, _, direct = _run(tmp_path, source)
    total = len(source.splitlines())
    assert direct and indirect
    for e in [*direct, *indirect.values()]:
        assert e.file == "models/m.sql" and not e.model_level_citation, e
        assert 1 <= e.lines[0] <= e.lines[1] <= total, e
    name = next(e for e in direct if e.to_column.endswith(".name"))
    assert name.lines == (7, 7)  # c.name in the final SELECT
    assert indirect[("orders.user_id", "m.name", "JOIN")].lines == (11, 11)
