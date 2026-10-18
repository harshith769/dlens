"""dlens.gold_spec: the D7 expansion (DESIGN_v2 §10 D7) and the gold-answer helpers (S09)."""

from pathlib import Path

import pytest
import yaml

from dlens import gold_spec as gs
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


# ------------------------------------------------------------------ gold answers (S09 step 3)
SS = Path(__file__).parents[2] / "corpora" / "synthetic_shop"

TOY = {
    "seeds": {"raw_a": ["x", "y", "k"]},
    "models": {
        "stg_a": {"depends_on": ["raw_a"], "columns": ["x", "y", "k"]},
        "int_b": {"depends_on": ["stg_a"], "columns": ["total"]},
        "fct_c": {"depends_on": ["int_b"], "columns": ["total"]},
    },
    "edges": [
        {"from": "raw_a.x", "to": "stg_a.x", "kind": "IDENTITY"},
        {"from": "raw_a.y", "to": "stg_a.y", "kind": "IDENTITY"},
        {"from": "raw_a.k", "to": "stg_a.k", "kind": "RENAME"},
        {"from": "stg_a.x", "to": "int_b.total", "kind": "AGGREGATION"},
        {"from": "stg_a.y", "to": "int_b.total", "kind": "AGGREGATION"},
        {"from": "int_b.total", "to": "fct_c.total", "kind": "IDENTITY"},
    ],
    "indirect_edges": [
        {"from": "stg_a.k", "model": "int_b", "type": "GROUP_BY", "phase": "v0.3", "targets": "all"}
    ],
}


def test_closures_direct_vs_with_indirect() -> None:
    v = gs.build_view(TOY)
    assert gs.downstream(v, "raw_a.k", with_indirect=False) == {"stg_a.k"}
    assert gs.downstream(v, "raw_a.k", with_indirect=True) == {
        "stg_a.k",
        "int_b.total",
        "fct_c.total",
    }
    assert gs.upstream(v, "fct_c.total", with_indirect=False) == {
        "int_b.total",
        "stg_a.x",
        "stg_a.y",
        "raw_a.x",
        "raw_a.y",
    }
    assert "raw_a.k" in gs.upstream(v, "fct_c.total", with_indirect=True)
    assert not gs.reaches(v, "raw_a.k", "fct_c.total", with_indirect=False)
    assert gs.reaches(v, "raw_a.k", "fct_c.total", with_indirect=True)


def test_inputs_depths_and_paths() -> None:
    v = gs.build_view(TOY)
    assert [e["from"] for e in gs.direct_inputs(v, "int_b.total")] == ["stg_a.x", "stg_a.y"]
    assert [(x.from_column, x.type) for x in gs.indirect_inputs(v, "int_b.total")] == [
        ("stg_a.k", "GROUP_BY")
    ]
    assert gs.downstream_depth(v, "raw_a.x") == 3 and gs.downstream_depth(v, "fct_c.total") == 0
    depths = gs.compute_depths(v)
    # tie between raw_a.x and raw_a.y: the lexicographically largest path wins (Appendix B rule)
    assert gs.longest_path(v, "fct_c.total", depths) == [
        "raw_a.y",
        "stg_a.y",
        "int_b.total",
        "fct_c.total",
    ]


def test_exposures_and_edge_lines() -> None:
    exposures = {"fin": ["fct_c"], "mkt": ["fct_d"]}
    assert gs.exposures_reached({"fct_c", "int_b"}, exposures) == ["fin"]
    text = "edges:\n  - {from: a.x,  to: b.y, kind: RENAME}\n  - {from: b.y, to: c.z}\n"
    assert gs.edge_lines(text) == {("a.x", "b.y"): 2, ("b.y", "c.z"): 3}


def test_longest_path_reproduces_appendix_b() -> None:
    v = gs.build_view(yaml.safe_load((SS / "lineage_spec.yml").read_text()))
    exp = yaml.safe_load((SS / "spec_expected.yml").read_text())
    depths = gs.compute_depths(v)
    rows = exp["deep_columns"]
    assert len(rows) == 55
    assert [r["column"] for r in rows if gs.longest_path(v, r["column"], depths) != r["path"]] == []


def test_edge_lines_cover_every_direct_edge() -> None:
    text = (SS / "lineage_spec.yml").read_text()
    v = gs.build_view(yaml.safe_load(text))
    lines = gs.edge_lines(text)
    assert v.direct_pairs <= set(lines)
