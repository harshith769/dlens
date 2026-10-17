import ast
from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest

from dlens_oracle.build import Corpus, OracleError, Warehouse, _topological, fingerprint
from dlens_oracle.controls import determinism, row_order

PACKAGE = Path(__file__).parents[3] / "eval" / "oracle" / "dlens_oracle"
ALLOWED_DLENS = {"dlens.gold_spec"}


def test_oracle_imports_only_the_gold_side_of_dlens() -> None:
    """oracle-design.md §0: no engine, ingest or graph import, so no parser output can leak in."""
    found = []
    for path in sorted(PACKAGE.glob("*.py")):
        for node in ast.walk(ast.parse(path.read_text())):
            names = (
                [a.name for a in node.names]
                if isinstance(node, ast.Import)
                else [node.module or ""]
                if isinstance(node, ast.ImportFrom)
                else []
            )
            found += [(path.name, n) for n in names if n.split(".")[0] == "dlens"]
    assert {n for _, n in found} <= ALLOWED_DLENS, found


def test_fingerprint_ignores_row_order_and_sees_values() -> None:
    a = fingerprint(["x", "y"], [(1, "a"), (2, "b")])
    assert fingerprint(["x", "y"], [(2, "b"), (1, "a")]) == a
    assert fingerprint(["x", "y"], [(1, "a"), (3, "b")]).changed(a) == ["x"]


def test_fingerprint_blind_spot_permutation_across_rows() -> None:
    """Documented blind spot: swapping values between rows keeps every column's multiset."""
    a = fingerprint(["k", "v"], [(1, "a"), (2, "b")])
    assert fingerprint(["k", "v"], [(1, "b"), (2, "a")]).changed(a) == []


def test_fingerprint_null_and_row_count() -> None:
    a = fingerprint(["x"], [(1,), (2,)])
    assert fingerprint(["x"], [(1,), (None,)]).changed(a) == ["x"]
    b = fingerprint(["x", "y"], [(1, 1), (2, 2)])
    assert fingerprint(["x", "y"], [(1, 1)]).changed(b) == ["x", "y"]  # row count: all columns


def test_fingerprint_types_are_exact_and_doubles_rounded() -> None:
    assert fingerprint(["x"], [(0.1 + 0.2,)]) == fingerprint(["x"], [(0.3,)])
    assert fingerprint(["x"], [(Decimal("1.50"),)]) != fingerprint(["x"], [(Decimal("1.51"),)])
    assert fingerprint(["x"], [(date(2025, 1, 1),)]) != fingerprint(["x"], [("2025-01-01",)])
    assert fingerprint(["x"], [(True,)]) != fingerprint(["x"], [(1,)])


def test_topological_is_deterministic_and_rejects_cycles() -> None:
    assert _topological({"c": ["a", "b"], "b": ["a"], "a": []}) == ["a", "b", "c"]
    with pytest.raises(OracleError):
        _topological({"a": ["b"], "b": ["a"]})


def test_children_and_downstream(toy: Corpus) -> None:
    assert toy.children["raw_orders"] == ["stg_orders"]
    assert toy.children["stg_orders"] == ["orders_users", "first_per_user"]
    assert toy.children["orders_users"] == []
    assert toy.downstream("raw_orders") == ["stg_orders", "orders_users", "first_per_user"]
    assert toy.downstream("raw_users") == ["orders_users"]


def test_warehouse_materialises_and_restores(warehouse: Warehouse) -> None:
    base = warehouse.table_fingerprint("orders_users", "base")
    assert base.rows == 3
    assert warehouse.types("raw_orders")["amount"] == "DECIMAL(10,2)"
    values = warehouse.column_values("raw_users", "name")
    warehouse.write_column("raw_users", "name", [v.upper() for v in values])  # type: ignore[union-attr]
    assert warehouse.model_fingerprint("orders_users").changed(base) == ["name"]
    warehouse.restore("raw_users")
    assert warehouse.model_fingerprint("orders_users") == base


def test_write_column_keeps_type_and_other_columns(warehouse: Warehouse) -> None:
    values = warehouse.column_values("raw_orders", "amount")
    warehouse.write_column("raw_orders", "amount", [None] * len(values))
    rows = warehouse.con.execute('SELECT id, amount FROM main."raw_orders" ORDER BY id').fetchall()
    assert [r[0] for r in rows] == [1, 2, 3, 4, 5] and {r[1] for r in rows} == {None}
    assert warehouse.con.execute('DESCRIBE main."raw_orders"').fetchall()[2][1] == "DECIMAL(10,2)"


def test_controls(toy: Corpus, warehouse: Warehouse) -> None:
    assert determinism(toy, warehouse) == []
    sensitive = row_order(warehouse, seed=1)
    # first_per_user picks an arbitrary order among ties: its order_id depends on row order
    assert set(sensitive.columns) == {"first_per_user.order_id"}
    assert sensitive.columns["first_per_user.order_id"] == ["stg_orders"]
    assert warehouse.table_fingerprint("stg_orders") == warehouse.table_fingerprint(
        "stg_orders", "base"
    )
