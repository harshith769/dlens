from collections import Counter
from datetime import date, datetime, timedelta
from decimal import Decimal

import pytest

from dlens_oracle import modes
from dlens_oracle.build import Warehouse

INTS = [3, 1, None, 4, 1, 5]
DECS = [Decimal("1.50"), Decimal("2.00"), None, Decimal("9.99")]
DATES = [date(2025, 1, 1), date(2025, 3, 1), None, date(2025, 2, 1)]
TS = [datetime(2025, 1, 1, 8), datetime(2025, 1, 2, 9), None]
STRS = ["a", "b", "a", None, "c"]
BOOLS = [True, False, None, True]


@pytest.mark.parametrize(
    ("sql_type", "expected"),
    [
        ("INTEGER", "integer"),
        ("BIGINT", "integer"),
        ("DECIMAL(10,2)", "numeric"),
        ("DOUBLE", "numeric"),
        ("DATE", "temporal"),
        ("TIMESTAMP", "temporal"),
        ("TIMESTAMP WITH TIME ZONE", "temporal"),
        ("VARCHAR", "string"),
        ("BOOLEAN", "boolean"),
        ("INTEGER[]", "other"),
    ],
)
def test_type_class(sql_type: str, expected: str) -> None:
    assert modes.type_class(sql_type) == expected


CASES = [("INTEGER", INTS), ("DECIMAL(10,2)", DECS), ("DATE", DATES), ("TIMESTAMP", TS),
         ("VARCHAR", STRS), ("BOOLEAN", BOOLS)]  # fmt: skip


@pytest.mark.parametrize(("sql_type", "values"), CASES)
def test_every_mode_is_deterministic_and_changes_something(sql_type: str, values: list) -> None:
    for mode in modes.modes_for(sql_type):
        a = modes.apply(mode, sql_type, values, "t.c")
        assert a == modes.apply(mode, sql_type, values, "t.c"), mode
        assert a is not None and len(a) == len(values), mode
        assert a != values, mode
        if mode in modes.MULTISET_PRESERVING:
            assert Counter(map(str, a)) == Counter(map(str, values)), mode
        else:
            assert Counter(map(str, a)) != Counter(map(str, values)), mode


def test_seed_and_column_pick_the_subset() -> None:
    values = list(range(40))
    assert modes.apply("null_out", "INTEGER", values, "t.a") != modes.apply(
        "null_out", "INTEGER", values, "t.b"
    )
    assert modes.apply("null_out", "INTEGER", values, "t.a", seed=1) != modes.apply(
        "null_out", "INTEGER", values, "t.a", seed=2
    )
    assert modes.apply("null_out", "INTEGER", values, "t.a").count(None) == 20


def test_integer_modes() -> None:
    assert modes.apply("relabel", "INTEGER", INTS, "t.c") == [
        1_000_006, 1_000_004, None, 1_000_007, 1_000_004, 1_000_008
    ]  # fmt: skip
    assert modes.apply("scale", "INTEGER", [1, 2], "t.c") == [3, 6]
    keys = [3, 1, 4, 1, 5, 9]
    broken = modes.apply("break", "INTEGER", keys, "t.c")
    assert broken is not None
    fresh = [v for v, old in zip(broken, keys, strict=True) if v != old]
    assert len(fresh) == 3 and not set(fresh) & set(keys)  # new keys: no match anywhere
    crossed = modes.apply("cross", "INTEGER", [2, 2, 2, 2], "t.c")
    assert sorted(crossed or []) == [-2, -2, 20, 20]


def test_numeric_temporal_string_boolean_modes() -> None:
    assert modes.apply("shift", "DECIMAL(10,2)", [Decimal("1.00")], "t.c") == [Decimal("8.31")]
    assert modes.apply("shift", "DOUBLE", [1.0], "t.c") == [pytest.approx(8.31)]
    assert modes.apply("scale", "DECIMAL(10,2)", [Decimal("2.25")], "t.c") == [Decimal("3.38")]
    assert modes.apply("shift", "DATE", DATES, "t.c") == [
        None if d is None else d + timedelta(days=37) for d in DATES
    ]
    crossed = modes.apply("cross", "DATE", [date(2025, 6, 1)] * 2, "t.c")
    assert sorted(crossed or []) == [date(2025, 2, 1), date(2025, 9, 29)]
    assert modes.apply("remap_existing", "VARCHAR", STRS, "t.c") == ["b", "b", "b", None, "c"]
    assert modes.apply("remap_new", "VARCHAR", STRS, "t.c") == [
        "zz_oracle", "b", "zz_oracle", None, "c"
    ]  # fmt: skip
    assert modes.apply("remap_existing", "VARCHAR", ["x", "x"], "t.c") is None
    assert modes.apply("flip", "BOOLEAN", BOOLS, "t.c") == [False, True, None, False]


def test_written_values_keep_the_column_type(warehouse: Warehouse) -> None:
    for table, column in [("raw_orders", "amount"), ("raw_orders", "placed"),
                          ("raw_users", "vip"), ("raw_orders", "status")]:  # fmt: skip
        sql_type = warehouse.types(table)[column]
        for mode in modes.modes_for(sql_type):
            new = modes.apply(mode, sql_type, warehouse.column_values(table, column), column)
            assert new is not None
            warehouse.write_column(table, column, new)
            got = warehouse.con.execute(f'SELECT "{column}" FROM main."{table}" ORDER BY rowid')
            assert [r[0] for r in got.fetchall()] == new, (column, mode)
            described = warehouse.con.execute(f'DESCRIBE main."{table}"').fetchall()
            assert {r[0]: r[1] for r in described}[column] == sql_type
            warehouse.restore(table)
