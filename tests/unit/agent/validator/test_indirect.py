"""Indirect edges in the validator (s12-design A5, ADR 0026): R3 checks a citation by edge kind
(the same rule as metrics M7 (iv), on shared cases), provenance cites indirect edges by kind, R8c
never bridges through an indirect edge, and the r_ fact's verdict uses direct + indirect hops."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import pytest

from dlens.agent.tools import Toolbox
from dlens.agent.tools.provenance import Provenance
from dlens.agent.tools.reach import check, fact_record
from dlens.agent.validator import ValidationContext, _citation_problem, validate
from dlens.graph import LineageGraph
from dlens.lineage import IndirectEdge, IndirectKind

from ..loop.conftest import write_shop
from ..tools.conftest import GROUP_BY_X_ID, make_shop
from .conftest import answer, eid

FIX = Path(__file__).resolve().parents[3] / "fixtures" / "citations"
SPEC = json.loads((FIX / "indirect_cases.json").read_text())
EMPTY = LineageGraph(
    columns={}, edges=[], depends_on=[], consumes=[], models={}, exposures={}, parse={}
)


@dataclass
class _Ledger:
    graph: LineageGraph
    project_dir: Path
    log: list[Any] = field(default_factory=list)

    @property
    def emitted_ids(self) -> frozenset[str]:
        return frozenset()

    def record(self, item_id: str) -> dict[str, Any] | None:
        return None


@pytest.mark.parametrize("case", SPEC["cases"], ids=[c["name"] for c in SPEC["cases"]])
def test_r3_on_the_shared_indirect_cases(case: dict) -> None:
    """Accepts exactly the citations metrics M7 accepts (tests/unit/eval/
    test_indirect_citation_cases.py reads the same file)."""
    a, b = case["lines"]
    rec = {
        "edge_id": "e_x",
        "from": f"model.p.{case['from']}",
        "to": f"model.p.{case['to']}",
        "kind": case["kind"],
        "key": case["key"],
        "indirect": True,
        "citation": {"file": SPEC["file"], "line_start": a, "line_end": b, "level": "line"},
    }
    ctx = ValidationContext(ledger=_Ledger(EMPTY, FIX))
    assert (_citation_problem("e_x", rec, ctx) is None) is case["valid"]


def test_r3_keeps_the_to_name_rule_for_direct_edges() -> None:
    """The same lines and columns as a direct edge: the `to` column must be named."""
    rec = {
        "from": "model.p.stg_orders.customer_id",
        "to": "model.p.fct_x.lifetime",
        "kind": "IDENTITY",
        "citation": {"file": SPEC["file"], "line_start": 11, "line_end": 11, "level": "line"},
    }
    ctx = ValidationContext(ledger=_Ledger(EMPTY, FIX))
    assert "does not contain 'lifetime'" in (_citation_problem("e_x", rec, ctx) or "")


def _cites(project: Path, edge: IndirectEdge, sql: str) -> str:
    (project / "models").mkdir(parents=True, exist_ok=True)
    (project / edge.file).write_text(sql)
    return Provenance(make_shop([edge]), project).edge_citation(edge).level


def _edge(key: str, lines: tuple[int, int]) -> IndirectEdge:
    return IndirectEdge(
        from_column="model.p.stg.x_id",
        to_column="model.p.fct.total",
        kind=IndirectKind.JOIN,
        key=key,
        expression="join",
        file="models/j.sql",
        lines=lines,
        model_level_citation=False,
    )


def test_provenance_cites_indirect_edges_by_kind(tmp_path: Path) -> None:
    from_name = "select 1\nfrom a join b on a.x_id = b.x_id\n"
    assert _cites(tmp_path / "a", _edge("a.x_id", (2, 2)), from_name) == "line"
    cte = "with src as (\n  select id as k from t\n)\nselect * from src where src.k > 0\n"
    assert _cites(tmp_path / "b", _edge("src.k", (4, 4)), cte) == "line"  # key under the guard
    cast = "select cast(k as int) as amount\nfrom t where amount.k > 0\n"
    assert _cites(tmp_path / "c", _edge("amt.k", (2, 2)), cast) == "model"  # not a relation
    star = "select *\nfrom t\n"
    assert _cites(tmp_path / "d", _edge("t.y", (1, 1)), star) == "model"  # never "star"


def test_indirect_edge_records_carry_key_and_flag(box: Toolbox) -> None:
    mixed = Toolbox(make_shop([GROUP_BY_X_ID]), box.project_dir)
    r = mixed.call("trace_upstream", {"column_id": "fct.total", "include_indirect": True})
    recs = [r.side_records["edges"][i] for i in r.side_records["edges"]]
    indirect = [x for x in recs if x.get("indirect")]
    assert [(x["kind"], x["key"]) for x in indirect] == [("GROUP_BY", "stg.x_id")]
    assert all("key" not in x and "indirect" not in x for x in recs if x not in indirect)
    assert indirect[0]["citation"]["level"] == "line"  # "group by x_id" names x_id


# -- R8c: direct-only bridges ----------------------------------------------------------------


def test_r8c_never_bridges_through_an_indirect_edge(shop_root: Path) -> None:
    """stg.x_id -> fct.total exists only as GROUP_BY. A claim naming both, anchored by the edge
    raw.id -> stg.x_id, would be completed by a bridge through the GROUP_BY edge if R8c used
    indirect edges; it must fail R8 instead."""
    tb = Toolbox(make_shop([GROUP_BY_X_ID]), shop_root)
    tb.call("trace_upstream", {"column_id": "fct.total", "include_indirect": True})
    anchor = eid(tb, "raw.id", "stg.x_id")
    a = answer(
        "raw.id feeds stg.x_id, which feeds fct.total.", ("raw.id feeds fct.total", [anchor])
    )
    r = validate(a, tb)
    assert r.completions == []
    assert "R8" in [f.rule for f in r.failures]


# -- R9 fact: direct + indirect verdict, both readings stated --------------------------------


def test_fact_on_a_direct_no_indirect_yes_pair(tmp_path: Path) -> None:
    g = make_shop([GROUP_BY_X_ID])
    src, dst = g.resolve("raw.id"), g.resolve("fct.total")
    rec = fact_record(g, check(g, src, dst))
    assert rec["reaches"] is True and rec["hops"] == 2
    assert rec["direct_reaches"] is False and rec["direct_hops"] is None
    assert rec["fact"] == (
        "raw.id reaches fct.total in 2 hops "
        "(graph check: with indirect dependencies; not through direct edges)"
    )
    plain = make_shop()
    rec0 = fact_record(plain, check(plain, plain.resolve("raw.id"), plain.resolve("fct.total")))
    assert rec0["reaches"] is False and rec0["fact"].endswith("(graph check: direct or indirect)")


def test_r9_holds_the_answer_to_the_indirect_verdict(tmp_path: Path) -> None:
    tb = Toolbox(make_shop([GROUP_BY_X_ID]), write_shop(tmp_path / "p"))
    r = tb.call("reachability", {"from_column": "raw.id", "to_column": "fct.total"}, code=True)
    rid = r.llm_payload["fact_id"]
    no = answer("No, raw.id does not affect fct.total.", verdict="no")
    assert [f.rule for f in validate(no, tb).failures] == ["R9", "R9"]
    yes = answer(
        "Yes, raw.id affects fct.total through the group by key.",
        ("raw.id reaches fct.total", [rid]),
        verdict="yes",
    )
    res = validate(yes, tb)
    assert res.passed, res.failures
    assert "[GROUP_BY]" in " ".join(r.llm_payload["path"])
