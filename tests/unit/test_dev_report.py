"""scripts/dev_report.py scoring (pure functions; no model, no corpus build)."""

import importlib.util
import json
from pathlib import Path

ROOT = Path(__file__).parents[2]
_spec = importlib.util.spec_from_file_location("dev_report", ROOT / "scripts" / "dev_report.py")
assert _spec and _spec.loader
dr = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(dr)

E = {"e_1": ("a.x", "b.x"), "e_2": ("b.x", "c.x"), "e_3": ("z.y", "c.x")}


def edge_of(i):
    return E.get(i)


def q(**expect):
    gold = expect.pop("gold", [("a.x", "b.x"), ("b.x", "c.x")])
    return {
        "id": "t",
        "gold": {"edges": [{"from": f, "to": t} for f, t in gold], **expect.pop("gold_extra", {})},
        "expect": {"verdict": "answered", **expect},
    }


def ans(*claims, text="c.x comes from a.x.", **kw):
    return {
        "answer_text": text,
        "claims": [{"text": "x", "edge_ids": list(ids), "chunk_ids": []} for ids in claims],
        **kw,
    }


REC = {"validation": {"passed": True, "repairs": []}, "tokens": {"llm_calls": 3}}


def test_dev_questions_are_twenty_with_unique_ids_and_spec_lines():
    qs = dr.load_questions()
    assert len(qs) == 20 and len({x["id"] for x in qs}) == 20
    for x in qs:
        assert x["source_lines"] and x["split"] == "dev"
        assert all("line" in e for e in x["gold"]["edges"])
    refusal_ok = {x["id"] for x in qs if x["expect"].get("or_refused")}
    assert refusal_ok == {"dev-17", "dev-18"}  # dev-10's "no" is answerable: no refusal


def test_recall_extra_and_pass():
    row = dr.score(q(must_cite=[[{"from": "b.x", "to": "c.x"}]]), ans(["e_2", "e_3"]), REC, edge_of)
    assert row["pass"] and row["recall"] == 0.5
    assert row["extra_edges"] == [("z.y", "c.x")] and row["outcome"] == "pass"


def test_missing_must_cite_group_fails():
    row = dr.score(q(must_cite=[[{"from": "a.x", "to": "b.x"}]]), ans(["e_2"]), REC, edge_of)
    assert not row["pass"] and row["reasons"][0].startswith("missing a.x->b.x")


def test_also_ok_is_not_extra_and_forbidden_fails():
    question = q(
        gold_extra={"also_ok": [{"from": "z.y", "to": "c.x"}]},
        forbid_edges=[{"from": "a.x", "to": "b.x"}],
    )
    row = dr.score(question, ans(["e_1", "e_3"]), REC, edge_of)
    assert row["extra_edges"] == [] and "cites a forbidden edge" in row["reasons"]


def test_refusal_passes_only_where_accepted():
    refused = {"answer_text": "I can't answer", "refused": True, "claims": []}
    assert not dr.score(q(), refused, {}, edge_of)["pass"]
    assert dr.score(q(or_refused=True), refused, {}, edge_of)["pass"]
    assert dr.score(q(verdict="refused"), refused, {}, edge_of)["pass"]


def test_chain_verdict_needs_the_downstream_column():
    rec = {**REC, "ambiguity": {"mode": "chain", "downstream": "c.x"}}
    assert dr.score(q(verdict="chain", downstream="c.x"), ans(["e_2"]), rec, edge_of)["pass"]
    assert not dr.score(q(verdict="chain", downstream="b.x"), ans(["e_2"]), rec, edge_of)["pass"]
    assert not dr.score(q(), ans(["e_2"]), rec, edge_of)["pass"]  # chain not in modes_ok
    assert dr.score(q(modes_ok=[None, "chain"]), ans(["e_2"]), rec, edge_of)["pass"]


def test_or_excerpt_of_satisfies_must_cite():
    question = q(must_cite=[[{"from": "a.x", "to": "b.x"}]], or_excerpt_of="b")
    a = {"answer_text": "t", "claims": [{"text": "x", "edge_ids": [], "chunk_ids": ["s_1"]}]}
    assert dr.score(question, a, REC, edge_of, {"s_1": "b"})["pass"]


def test_yes_no_heuristic():
    assert dr.yes_no("No. amt only reaches net_paid_usd.") == "no"
    assert dr.yes_no("Yes, it flows through items_subtotal.") == "yes"
    assert dr.yes_no("raw_payments.amt does not affect lifetime_value.") == "no"
    assert dr.yes_no("It flows to fct_orders.") is None
    row = dr.score(q(yes_no="no"), ans(["e_1"], text="Yes, it does."), REC, edge_of)
    assert any("heuristic" in r for r in row["reasons"])


def test_direct_claim_is_flagged_but_negated_is_not():
    question = q(forbid_edges=[{"from": "a.x", "to": "c.x"}], no_direct_claim=True)
    bad = {"answer_text": "t", "claims": [{"text": "c.x comes directly from a.x", "edge_ids": []}]}
    ok = {"answer_text": "t", "claims": [{"text": "c.x does not come directly from a.x"}]}
    assert "claims a direct link" in dr.score(question, bad, REC, edge_of)["reasons"]
    assert "claims a direct link" not in dr.score(question, ok, REC, edge_of)["reasons"]


def test_validator_outcomes():
    out = dr.validator_outcome
    assert out({}, {}) == "n/a"
    assert out({}, {"validation": {"skipped": True}}) == "n/a"
    assert out({"refused": True}, {"validation": {"warning": True}}) == "refused"
    assert out({}, {"validation": {"warning": True}}) == "warning"
    assert out({}, {"validation": {"regenerated": True}}) == "regenerated"
    assert out({}, {"validation": {"completions": [{}]}}) == "completed"
    assert out({}, {"validation": {"repairs": [{}]}}) == "repaired"
    assert out({}, {"validation": {"repairs": []}}) == "pass"


def test_shortest_path_is_undirected_and_bounded():
    edges = [("a", "b"), ("b", "c"), ("d", "c")]
    assert dr.shortest_path(edges, "a", "d", None) == 3
    assert dr.shortest_path(edges, "a", "d", 2) is None
    assert dr.shortest_path(edges, "a", "zz", None) is None


def test_r8_drops_counts_completable_claims():
    rec = {
        "draft": {"claims": [{}, {}, {}]},
        "validation": {
            "first": {
                "failures": [
                    {"claim_index": 0, "rule": "R8", "item_id": "a.x,c.x"},  # completable
                    {"claim_index": 1, "rule": "R8", "item_id": "a.x,q.q"},  # no path
                    {"claim_index": 1, "rule": "R7", "item_id": "a.x"},
                    {"claim_index": None, "rule": "R4.hallucinated", "item_id": "q.q"},
                ]
            }
        },
    }
    out = dr.r8_drops(rec, list(E.values()))
    assert out == {
        "claims": 3,
        "r8": 2,
        "r8_only": 1,
        "completable": 1,
        "completable_4": 1,
        "completed": 0,
    }


def test_r8_drops_counts_completed_claims_as_completable():
    rec = {
        "draft": {"claims": [{}, {}]},
        "validation": {"first": {"failures": [], "completions": [{"claim_index": 1}]}},
    }
    out = dr.r8_drops(rec, [])
    assert out["completable"] == 1 and out["completed"] == 1 and out["claims"] == 2


def test_r8_line_applies_the_fixed_threshold():
    assert "do NOT implement" in dr.r8_line({"claims": 100, "completable": 9} | _z())
    assert "IMPLEMENT" in dr.r8_line({"claims": 100, "completable": 10} | _z())


def _z():
    return {"r8": 0, "r8_only": 0, "completable_4": 0}


def test_summary_totals():
    rows = [
        dr.score(q(), ans(["e_1", "e_2"]), REC, edge_of),
        dr.score(q(), {"answer_text": "x", "refused": True}, {}, edge_of),
    ]
    s = dr.summary(rows)
    assert s["questions"] == 2 and s["pass"] == 1 and s["mean_recall"] == 1.0
    assert json.dumps(s)  # serialisable


def test_claim_tiers_split_raw_repaired_completed_failed():
    rec = {
        "draft": {"claims": [{}, {}, {}, {}]},
        "validation": {
            "first": {
                "dropped_claims": [3],
                "repairs": [{"claim_index": 1}, {"claim_index": 2}],
                "completions": [{"claim_index": 2}],
            }
        },
    }
    assert dr.claim_tiers(rec) == {"raw": 1, "repaired": 1, "completed": 1, "failed": 1}
    assert dr.claim_tiers({"validation": {"skipped": True}})["raw"] == 0
