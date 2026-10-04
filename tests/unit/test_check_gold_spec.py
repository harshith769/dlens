"""scripts/check_gold_spec.py on small synthetic specs (one failing case per check)."""

import copy
import importlib.util
from pathlib import Path
from typing import Any

import pytest

ROOT = Path(__file__).parents[2]
_spec = importlib.util.spec_from_file_location(
    "check_gold_spec", ROOT / "scripts" / "check_gold_spec.py"
)
assert _spec and _spec.loader
cg = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(cg)


def e(src: str, dst: str, kind: str = "IDENTITY", traps: list[str] | None = None) -> dict:
    return {"from": src, "to": dst, "kind": kind, "phase": "v0.1", "traps": traps or []}


def ind(src: str, model: str, kind: str = "JOIN", targets: Any = "all", **kw: Any) -> dict:
    return {"from": src, "model": model, "type": kind, "phase": "v0.3", "targets": targets, **kw}


# raw_a -> stg_a -> int_b (joins stg_a with stg_c) ; int_b.n is window-only (no direct input)
BASE: dict[str, Any] = {
    "seeds": {"raw_a": ["id", "x"], "raw_c": ["id"]},
    "models": {
        "stg_a": {"depends_on": ["raw_a"], "columns": ["a_id", "x"]},
        "stg_c": {"depends_on": ["raw_c"], "columns": ["c_id"]},
        "int_b": {"depends_on": ["stg_a", "stg_c"], "columns": ["a_id", "x2", "n"]},
    },
    "edges": [
        e("raw_a.id", "stg_a.a_id", "RENAME"),
        e("raw_a.x", "stg_a.x"),
        e("raw_c.id", "stg_c.c_id", "RENAME"),
        e("stg_a.a_id", "int_b.a_id"),
        e("stg_a.x", "int_b.x2", "TRANSFORMATION", ["t1"]),
    ],
    "indirect_edges": [
        ind("stg_a.a_id", "int_b"),
        ind("stg_c.c_id", "int_b"),
        ind("stg_a.x", "int_b", "WINDOW", ["n"]),
    ],
}

EXPECTED: dict[str, Any] = {
    "counts": {
        "seeds": 2,
        "seed_columns": 3,
        "models": {"stg": 2, "int": 1},
        "model_columns": {"stg": 3, "int": 3},
        "direct_edges": 5,
        "direct_kinds": {"IDENTITY": 2, "RENAME": 2, "TRANSFORMATION": 1},
    },
    "depth_histogram": {1: 3, 2: 2, "n/a": 1},
    "depth_na": ["int_b.n"],
    "deep_columns": [],
    "six_plus_by_model": {},
    "absent_columns": [{"column": "stg_a.ghost", "why": "test"}],
    "unreachable": [{"from": "raw_c.id", "to": "int_b.x2", "modes": ["direct"], "why": "test"}],
}


def spec(**changes: Any) -> dict[str, Any]:
    s = copy.deepcopy(BASE)
    s.update(changes)
    return s


def failed(checks: list) -> dict[str, list[str]]:
    return {c.name: c.details for c in checks if c.gated and not c.ok}


def run(s: dict, expected: dict | None = None, **kw: Any) -> dict[str, list[str]]:
    return failed(cg.check_spec(s, expected, **kw))


def test_base_passes_every_check() -> None:
    assert run(spec(), EXPECTED, v1_spec={"edges": BASE["edges"][:3]}) == {}


def test_schema_rejects_bad_kind_phase_and_keys() -> None:
    s = spec()
    s["edges"][0]["kind"] = "JOIN"
    s["indirect_edges"][0]["phase"] = "v0.1"
    s["indirect_edges"][1]["extra"] = 1
    (details,) = run(s).values()
    assert len(details) == 3


def test_schema_rejects_bad_targets_and_inventory_shape() -> None:
    s = spec()
    s["indirect_edges"][0]["targets"] = []
    s["models"]["stg_c"] = {"columns": ["c_id"]}
    assert len(run(s)["schema"]) == 2


def test_unknown_endpoints() -> None:
    s = spec()
    s["edges"].append(e("raw_a.zz", "int_b.x2"))
    s["indirect_edges"].append(ind("stg_a.x", "int_b", "FILTER", ["ghost"]))
    details = run(s)["endpoints"]
    assert any("raw_a.zz" in d for d in details)
    assert any("ghost" in d for d in details)


def test_duplicate_direct_edge() -> None:
    s = spec()
    s["edges"].append(e("raw_a.x", "stg_a.x", "RENAME"))
    assert "no duplicate edges" in run(s)


def test_duplicate_indirect_pair_same_type_but_not_other_type() -> None:
    s = spec()
    s["indirect_edges"].append(ind("stg_c.c_id", "int_b", "GROUP_BY"))
    assert run(s) == {}
    s["indirect_edges"].append(ind("stg_c.c_id", "int_b", "JOIN", ["x2"]))
    assert "no duplicate edges" in run(s)


def test_explicit_target_that_is_direct_fails() -> None:
    s = spec()
    s["indirect_edges"].append(ind("stg_a.x", "int_b", "FILTER", ["x2"]))
    assert "no pair both direct and indirect" in run(s)


def test_depends_on_missing_parent_and_parent_without_edges() -> None:
    s = spec()
    s["models"]["int_b"]["depends_on"] = ["stg_a"]
    assert any("stg_c not in depends_on" in d for d in run(s)["depends_on"])
    s = spec()
    s["models"]["int_b"]["depends_on"].append("raw_a")
    assert run(s)["depends_on"] == ["depends_on(int_b): raw_a contributes no edge"]


def test_parent_with_only_indirect_edges_is_fine() -> None:
    s = spec()  # stg_c reaches int_b only through the JOIN row
    assert "depends_on" not in run(s)


def test_column_without_any_incoming_edge() -> None:
    s = spec(indirect_edges=BASE["indirect_edges"][:2])  # drop the WINDOW row into int_b.n
    s["indirect_edges"] = [
        ind("stg_a.a_id", "int_b", targets=["x2"]),
        ind("stg_c.c_id", "int_b", targets=["x2"]),
    ]
    details = run(s)["every model column has an incoming edge (D3)"]
    assert details == ["int_b.n has no incoming edge"]


def test_counts_mismatch() -> None:
    exp = copy.deepcopy(EXPECTED)
    exp["counts"]["direct_kinds"]["IDENTITY"] = 3
    assert "direct_kinds" in run(spec(), exp)["counts (DESIGN_v2 §0, §2)"][0]


def test_depth_ignores_indirect_edges_and_checks_histogram() -> None:
    v = cg.build_view(spec())
    assert cg.compute_depths(v) == {
        "stg_a.a_id": 1, "stg_a.x": 1, "stg_c.c_id": 1,
        "int_b.a_id": 2, "int_b.x2": 2, "int_b.n": None,
    }  # fmt: skip
    exp = copy.deepcopy(EXPECTED)
    exp["depth_histogram"] = {1: 3, 2: 3}
    assert "depth histogram (DESIGN_v2 §5)" in run(spec(), exp)


def test_depth_cycle_is_reported() -> None:
    s = spec()
    s["edges"].append(e("int_b.x2", "stg_a.x"))
    s["models"]["stg_a"]["depends_on"].append("int_b")
    assert any("cycle" in d for d in run(s, EXPECTED)["depth"])


def _deep_spec() -> tuple[dict, dict]:
    """A 6-hop chain raw_s.v -> m1.v -> ... -> m6.v."""
    names = ["raw_s"] + [f"m{i}" for i in range(1, 7)]
    s = {
        "seeds": {"raw_s": ["v"]},
        "models": {
            n: {"depends_on": [p], "columns": ["v"]} for p, n in zip(names, names[1:], strict=False)
        },
        "edges": [e(f"{p}.v", f"{n}.v") for p, n in zip(names, names[1:], strict=False)],
    }
    exp = copy.deepcopy(EXPECTED)
    exp["counts"] = {}
    exp["depth_histogram"] = {i: 1 for i in range(1, 7)}
    exp["depth_na"] = []
    exp["unreachable"] = []
    exp["deep_columns"] = [{"column": "m6.v", "hops": 6, "path": [f"{n}.v" for n in names]}]
    exp["six_plus_by_model"] = {"m6": 1}
    return s, exp


def test_appendix_b_rows_and_paths() -> None:
    s, exp = _deep_spec()
    name = "6+ hop columns and paths (DESIGN_v2 Appendix B)"
    assert name not in run(s, exp)
    bad = copy.deepcopy(exp)
    bad["deep_columns"][0]["path"][3] = "m4.v"  # skips m3
    assert any("not a direct edge" in d for d in run(s, bad)[name])
    bad = copy.deepcopy(exp)
    bad["deep_columns"][0]["hops"] = 7
    assert run(s, bad)[name]
    bad = copy.deepcopy(exp)
    bad["deep_columns"] = []
    assert run(s, bad)[name] == ["m6.v: depth 6, not in Appendix B"]


def test_v1_edges_must_be_identical() -> None:
    v1 = {"edges": copy.deepcopy(BASE["edges"][:3])}
    v1["edges"][1]["kind"] = "RENAME"
    details = run(spec(), v1_spec=v1)["v1 direct edges content-identical (3 edges)"]
    assert details == [
        "only in v1: raw_a.x stg_a.x RENAME v0.1",
        "only in v2: raw_a.x stg_a.x IDENTITY v0.1",
    ]


def test_v1_edge_dropped_or_added_in_a_v1_model() -> None:
    v1 = {"edges": BASE["edges"][:3]}
    s = spec()
    s["edges"].append(e("raw_a.id", "stg_a.x", "TRANSFORMATION"))
    assert run(s, v1_spec=v1)["v1 direct edges content-identical (3 edges)"] == [
        "only in v2: raw_a.id stg_a.x TRANSFORMATION v0.1"
    ]


def test_absent_column_and_reachability() -> None:
    exp = copy.deepcopy(EXPECTED)
    exp["absent_columns"] = [{"column": "int_b.n", "why": "test"}]
    exp["unreachable"] = [
        {"from": "raw_a.x", "to": "int_b.x2", "modes": ["direct"], "why": "t"},
        {"from": "raw_c.id", "to": "int_b.x2", "modes": ["direct+indirect"], "why": "t"},
    ]
    got = run(spec(), exp)
    assert got["absent columns (DESIGN_v2 §1, §3)"] == ["int_b.n exists (test)"]
    assert len(got["unreachable pairs (DESIGN_v2 §1, §9 dev-10)"]) == 2  # 2nd only via the JOIN


def test_traps_references_and_tag_report() -> None:
    traps = {
        "traps": [
            {
                "id": "t1",
                "columns": ["int_b.x2"],
                "edges": ["stg_a.x -> int_b.x2", "stg_c.c_id -> int_b.n"],
                "paths": [["raw_a.x", "stg_a.x", "int_b.x2"]],
                "indirect": [{"from": "stg_c.c_id", "model": "int_b", "type": "JOIN"}],
                "absent_edges": ["stg_a.a_id -> stg_c"],
            }
        ],
        "exposures": [{"name": "d", "depends_on": ["int_b"]}],
    }
    checks = cg.check_spec(spec(), traps=traps)
    assert failed(checks) == {}
    (report,) = [c for c in checks if c.name.startswith("trap tags")]
    assert report.details == ["t1: listed, not tagged: raw_a.x -> stg_a.x"]  # not gated

    bad = copy.deepcopy(traps)
    bad["traps"][0]["edges"] = ["raw_a.x -> int_b.x2"]
    bad["traps"][0]["indirect"][0]["type"] = "FILTER"
    bad["traps"][0]["absent_edges"] = ["stg_a.a_id -> int_b"]
    bad["exposures"][0]["depends_on"] = ["ghost"]
    assert (
        len(failed(cg.check_spec(spec(), traps=bad))["traps reference spec models/columns/edges"])
        == 4
    )


@pytest.mark.parametrize("v1_models, label", [(set(), "new"), ({"int_b"}, "v1")])
def test_indirect_report_splits_v1_and_new_models(v1_models: set, label: str) -> None:
    v = cg.build_view(spec())
    lines = cg.indirect_report(v, v1_models).details
    join = next(x for x in lines if x.startswith("JOIN"))
    v1_part, new_part = join[12:41], join[41:]
    assert ("2 rows" in v1_part) == (label == "v1")
    assert ("2 rows" in new_part) == (label == "new")
    assert "pairs suppressed by D7 (direct edge wins): 1" in lines  # stg_a.a_id -> int_b.a_id
