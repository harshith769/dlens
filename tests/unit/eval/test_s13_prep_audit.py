"""scripts/s13_prep_audit.py: the outcome of each raw-draft claim missing from the validated
answer (dropped / rewritten / omitted / not validated) and its gold class."""

import importlib.util
from pathlib import Path
from typing import Any

import metrics as M

SCRIPT = Path(__file__).resolve().parents[3] / "scripts" / "s13_prep_audit.py"
spec = importlib.util.spec_from_file_location("s13_prep_audit", SCRIPT)
assert spec is not None and spec.loader is not None
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)

INV = M.Inventory(
    columns={"a_m.x", "b_m.y", "c_m.z", "d_m.w"},
    models={"a_m", "b_m", "c_m", "d_m"},
    seeds=set(),
    exposures=set(),
)
Q = {
    "id": "dev-01",
    "subtype": "upstream",
    "target": "a_m.x",
    "gold": {"verdict": "answered", "upstream": {"direct": ["b_m.y"], "all": ["b_m.y"]}},
}


def claim(text: str, origin: str | None = None) -> dict[str, Any]:
    return {"text": text, "ids": ["e_1"], **({"origin": origin} if origin else {})}


def record(draft: list[str], final: list[dict[str, Any]], **v: Any) -> dict[str, Any]:
    failures = v.pop("failures", [])
    return {
        "draft": {"claims": [claim(t) for t in draft]},
        "final_answer": {"claims": final},
        "validation": {
            "regenerated": v.pop("regenerated", False),
            "skipped": False,
            "first": {"failures": failures},
            "second": v.pop("second", None),
        },
        **v,
    }


def fail(i: int, rule: str) -> dict[str, Any]:
    return {"claim_index": i, "rule": rule, "item_id": "x", "message": "m"}


def test_kept_claims_are_not_listed_whatever_their_ids() -> None:
    rec = record(
        ["a_m.x comes from b_m.y.", "b_m.y comes from c_m.z"],
        [claim("a_m.x comes from b_m.y", "repaired"), claim("b_m.y comes from c_m.z", "completed")],
    )
    assert mod.audit_claims(rec, Q, INV) == []


def test_dropped_claim_gets_its_rule_and_gold_class() -> None:
    rec = record(
        ["a_m.x comes from b_m.y", "a_m.x comes from c_m.z", "It is a rename"],
        [],
        failures=[fail(0, "R8"), fail(1, "R4.hallucinated"), fail(2, "R7"), fail(None, "R2")],  # type: ignore[arg-type]
    )
    rows = mod.audit_claims(rec, Q, INV)
    assert [(r["outcome"], r["rules"], r["class"]) for r in rows] == [
        ("dropped", ["R8"], "consistent"),
        ("dropped", ["R4.hallucinated"], "inconsistent"),
        ("dropped", ["R7"], "no mention"),
    ]


def test_regenerate_rewritten_omitted_and_second_draft() -> None:
    rec = record(
        ["a_m.x comes from b_m.y", "b_m.y feeds a_m.x directly", "d_m.w is unrelated"],
        [claim("a_m.x is derived from b_m.y")],
        regenerated=True,
        failures=[fail(0, "R5"), fail(2, "R8")],
        second={"failures": [fail(1, "R8")]},
        regenerate_draft_raw='{"claims": [{"text": "a_m.x is derived from b_m.y", "ids": []},'
        ' {"text": "d_m.w again", "ids": []}]}',
    )
    rows = {r["claim_index"]: r for r in mod.audit_claims(rec, Q, INV)}
    assert rows[0]["outcome"] == rows[1]["outcome"] == "rewritten"  # same mentions, other text
    assert rows[2]["outcome"] == "dropped" and rows[2]["second"] == "failed R8"
    assert rows[2]["class"] == "inconsistent"
    rec["final_answer"]["claims"] = []
    rows = {r["claim_index"]: r for r in mod.audit_claims(rec, Q, INV)}
    assert rows[1]["outcome"] == "omitted"  # passed the first check, gone after the regenerate


def test_no_gold_set_for_ask_and_unanswerable() -> None:
    ask = {"id": "dev-77", "subtype": "meaning", "gold": {"verdict": "answered"}}
    assert mod.gold_nodes(ask) is None
    rec = record(["a_m.x comes from b_m.y"], [], failures=[fail(0, "R8")])
    assert mod.audit_claims(rec, ask, INV)[0]["class"] == "no gold set"


def test_gold_nodes_include_target_candidates_and_reach() -> None:
    q = {
        "id": "dev-10",
        "subtype": "yesno",
        "gold": {"verdict": "answered", "reach": {"from": "b_m.y", "to": "a_m.x", "path": []}},
    }
    assert mod.gold_nodes(q) == {"a_m.x", "b_m.y"}
    assert mod.gold_nodes(Q) == {"a_m.x", "b_m.y"}
