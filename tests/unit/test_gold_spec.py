"""dlens.gold_spec.expand_indirect: the D7 expansion of indirect spec rows (DESIGN_v2 §10 D7)."""

import pytest

from dlens.gold_spec import IndirectPair, expand_indirect

COLUMNS = {"m": ["k", "a", "b"]}


def row(src: str = "p.k", targets: object = "all", kind: str = "JOIN", **kw: object) -> dict:
    return {"from": src, "model": "m", "type": kind, "phase": "v0.3", "targets": targets, **kw}


def test_all_targets_every_column_of_the_model() -> None:
    exp = expand_indirect([row()], COLUMNS, set())
    assert [p.to_column for p in exp.pairs] == ["m.k", "m.a", "m.b"]
    assert {p.type for p in exp.pairs} == {"JOIN"}
    assert exp.suppressed == [] and exp.conflicts == []


def test_all_targets_drop_pairs_that_have_a_direct_edge() -> None:
    exp = expand_indirect([row()], COLUMNS, {("p.k", "m.k")})
    assert [p.to_column for p in exp.pairs] == ["m.a", "m.b"]
    assert exp.suppressed == [("p.k", "m.k", "JOIN")]
    assert exp.conflicts == []


def test_direct_edge_from_another_column_does_not_suppress() -> None:
    exp = expand_indirect([row()], COLUMNS, {("p.other", "m.k")})
    assert len(exp.pairs) == 3


def test_explicit_targets_taken_as_written_with_via() -> None:
    exp = expand_indirect([row(targets=["b", "a"], kind="GROUP_BY", via="agg")], COLUMNS, set())
    assert exp.pairs == [
        IndirectPair("p.k", "m.b", "GROUP_BY", "agg"),
        IndirectPair("p.k", "m.a", "GROUP_BY", "agg"),
    ]


def test_explicit_target_with_a_direct_edge_is_a_conflict() -> None:
    exp = expand_indirect([row(targets=["a", "b"])], COLUMNS, {("p.k", "m.a")})
    assert [p.to_column for p in exp.pairs] == ["m.b"]
    assert exp.conflicts == [("p.k", "m.a", "JOIN")]
    assert exp.suppressed == []


def test_same_pair_with_two_types_gives_two_pairs() -> None:
    exp = expand_indirect([row(), row(kind="GROUP_BY", targets=["a"])], COLUMNS, set())
    assert [(p.to_column, p.type) for p in exp.pairs if p.to_column == "m.a"] == [
        ("m.a", "JOIN"),
        ("m.a", "GROUP_BY"),
    ]


@pytest.mark.parametrize(
    "bad",
    [
        row(kind="LATERAL"),
        {**row(), "model": "nope"},
        row(targets=["zz"]),
        row(targets=[]),
        row(targets="some"),
    ],
)
def test_invalid_rows_raise(bad: dict) -> None:
    with pytest.raises(ValueError):
        expand_indirect([bad], COLUMNS, set())
