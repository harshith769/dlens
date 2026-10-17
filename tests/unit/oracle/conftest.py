"""A toy corpus for oracle unit tests: two seeds, three models, catalog "toy"."""

from pathlib import Path

import duckdb
import pytest

from dlens_oracle.build import Corpus, Model, Warehouse

SEEDS = {
    "raw_orders": (
        "id INTEGER, user_id INTEGER, amount DECIMAL(10,2), placed DATE, status VARCHAR",
        [
            (1, 10, "5.00", "2025-01-01", "done"),
            (2, 10, "7.50", "2025-01-03", "open"),
            (3, 11, "2.25", "2025-01-02", "done"),
            (4, 12, "9.00", "2025-01-05", "done"),
            (5, 13, "1.00", "2025-01-04", "open"),
        ],
    ),
    "raw_users": (
        "id INTEGER, name VARCHAR, vip BOOLEAN",
        [(10, "ann", True), (11, "bob", False), (12, "cy", False), (14, "dee", True)],
    ),
}

T = '"toy"."main"'
MODELS = [
    # one hop: rename + filter on status
    Model(
        "stg_orders",
        f"select id as order_id, user_id, amount, placed, status from {T}.raw_orders",
        ("raw_orders",),
    ),
    # LEFT JOIN users: name comes from the other side; amount from orders
    Model(
        "orders_users",
        f"select o.order_id, o.amount, u.name from {T}.stg_orders as o "
        f"left join {T}.raw_users as u on o.user_id = u.id where o.status = 'done'",
        ("stg_orders", "raw_users"),
    ),
    # order-sensitive on purpose: row_number over a key with ties
    Model(
        "first_per_user",
        f"select user_id, order_id from {T}.stg_orders "
        "qualify row_number() over (partition by user_id order by user_id) = 1",
        ("stg_orders",),
    ),
]


def make_corpus(tmp_path: Path) -> Corpus:
    db = tmp_path / "toy.duckdb"
    con = duckdb.connect(str(db))
    for name, (schema, rows) in SEEDS.items():
        con.execute(f"CREATE TABLE {name} ({schema})")
        con.executemany(f"INSERT INTO {name} VALUES ({', '.join('?' * len(rows[0]))})", rows)
    con.close()
    return Corpus("toy", sorted(SEEDS), {m.name: m for m in MODELS}, db)


@pytest.fixture
def toy(tmp_path: Path) -> Corpus:
    return make_corpus(tmp_path)


@pytest.fixture
def warehouse(toy: Corpus) -> Warehouse:
    return Warehouse(toy)
