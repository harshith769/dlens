from pathlib import Path

from dlens_oracle import thresholds as th
from dlens_oracle.build import Warehouse

MODELS = Path(__file__).parents[3] / "corpora" / "synthetic_shop" / "models"


def _model_sql() -> dict[str, str]:
    # Source and compiled SQL have the same lines (refs compile in place); the oracle run repeats
    # this check on the compiled SQL and records it in the results.
    return {p.stem: p.read_text() for p in sorted(MODELS.rglob("*.sql"))}


def test_thresholds_cover_every_predicate_line() -> None:
    """Amendment 3: every scan hit is a threshold or a not_thresholds entry with a reason."""
    spec = th.load()
    assert th.uncovered(_model_sql(), spec) == []
    assert th.stale(_model_sql(), spec) == []
    assert all(n.get("reason") for n in spec.not_thresholds)


def test_thresholds_file_is_well_formed() -> None:
    spec = th.load()
    ids = [t.id for t in spec.thresholds]
    assert len(ids) == len(set(ids))
    models = _model_sql()
    for t in spec.thresholds:
        assert t.model in models, t.id
        assert t.clause in {"FILTER", "CONDITIONAL", "JOIN", "direct"}, t.id
        assert t.inputs and all(len(i.split(".")) == 2 for i in t.inputs), t.id


def test_scan_finds_predicates_and_non_equi_joins() -> None:
    sql = "select a,\n case when b > 1 then 1 end\nfrom t join u\n on t.x = u.x\n and t.d <= u.d"
    assert [n for n, _ in th.scan(sql)] == [2, 4, 5]
    spec = th.ThresholdFile([], [{"model": "m", "line": 4, "reason": "equi-join key"}])
    assert th.uncovered({"m": sql}, spec) == [
        "m:2: case when b > 1 then 1 end",
        "m:5: and t.d <= u.d",
    ]


def test_probe_crossings(warehouse: Warehouse) -> None:
    probe = 'select id, amount, coalesce(amount > 4, false) from main."raw_orders"'
    t = th.Threshold(
        "big", "stg_orders", (1,), "amount > 4", "FILTER", (4.0,), ("raw_orders.amount",), probe
    )
    base, values = th.run_probe(warehouse, t)
    assert base == {1: True, 2: True, 3: False, 4: True, 5: False}
    warehouse.write_column("raw_orders", "amount", [v * 0 for v in values])  # type: ignore[operator]
    now, _ = th.run_probe(warehouse, t)
    assert th.crossings(base, now) == 3


def test_nearest_values() -> None:
    got = th.nearest([1, 29, 30, 31, None, 95], [30, 90])
    assert got[0] == {"cutoff": 30, "nearest_below": 29, "at_cutoff": 1, "nearest_above": 31,
                      "rows_below": 2, "rows_above": 2}  # fmt: skip
    assert got[1]["nearest_below"] == 31 and got[1]["nearest_above"] == 95
