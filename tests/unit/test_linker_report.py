"""scripts/linker_report.py: the report's metric definitions (design §7)."""

import importlib.util
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).parents[2]
_spec = importlib.util.spec_from_file_location(
    "linker_report", ROOT / "scripts" / "linker_report.py"
)
assert _spec and _spec.loader
lr = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(lr)


def fake(*ids: str, ambiguous: bool = False):
    cands = [{"id": i, "kind": "column", "match": "normalised", "score": 0.9} for i in ids]
    return lambda text: SimpleNamespace(
        payload={"candidates": cands, "ambiguous": ambiguous}, side={}
    )


def case(gold, amb=False, cid="c"):
    return {"id": cid, "variant": "v", "mention": "m", "gold": gold, "expect_ambiguous": amb}


def test_top1_top3_and_no_match():
    r = lr.run_case(fake("a.x", "b.y", "c.z"), case(["c.z"]))
    assert (r["top1"], r["top3"]) == (False, True)
    assert lr.run_case(fake(), case([]))["no_match_ok"] is True
    assert lr.run_case(fake("a.x"), case([]))["no_match_ok"] is False
    # full ids compare by their model.column suffix
    assert lr.run_case(fake("model.p.a.x"), case(["a.x"]))["top1"] is True


def test_ambiguity_rates():
    rows = [
        lr.run_case(fake("a.x", ambiguous=True), case(["a.x", "b.x"], amb=True)),
        lr.run_case(fake("a.x", ambiguous=True), case(["a.x"])),
        lr.run_case(fake("a.x"), case(["a.x"])),
        lr.run_case(fake(), case([])),
    ]
    m = lr.metrics(rows)
    assert m["ambiguous_rate"] == (2, 3)
    assert m["ambiguous_recall"] == (1, 1)
    assert m["false_ambiguous"] == (1, 2)
    assert m["no_match"] == (1, 1)
