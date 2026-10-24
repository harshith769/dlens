"""scripts/gen_dev_questions.py: 96 dev candidates from the dev pool, gold from the spec."""

import json
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).parents[2]
sys.path.insert(0, str(ROOT / "scripts"))
import gen_dev_questions as g  # noqa: E402

from dlens import gold_spec as gs  # noqa: E402

QUESTIONS = g.build()
MAIN = [q for q in QUESTIONS if not q.get("spare")]
CTX = g.load_ctx()

# The final count table (questions-design.md §1, as rebalanced in S09 step 5).
ROWS = {
    ("trace", "1"): 8, ("trace", "2-3"): 11, ("trace", "4-5"): 11, ("trace", "6+"): 11,
    ("false_premise", None): 4, ("impact", None): 24, ("yesno", None): 6, ("ask", None): 12,
    ("unanswerable", None): 9,
}  # fmt: skip
SUBTYPES = {"upstream": 24, "computed": 11, "ambiguous": 3, "multi_part": 3, "false_premise": 4,
            "downstream": 24, "yesno": 6, "meaning": 12}  # fmt: skip
WORDING = {"identifier": 48, "name_words": 18, "description": 10, "paraphrase": 20}


def row(q):
    if q["type"] == "trace" and q["subtype"] != "false_premise":
        return ("trace", q["hop_bucket"])
    if q["subtype"] == "false_premise":
        return ("false_premise", None)
    if q["subtype"] == "yesno":
        return ("yesno", None)
    return (q["type"], None)


def test_file_on_disk_is_fresh():
    assert g.OUT.read_text() == g.render(QUESTIONS), "run scripts/gen_dev_questions.py"


def test_count_table_subtypes_and_wording():
    assert len(MAIN) == 96 and len({q["id"] for q in QUESTIONS}) == len(QUESTIONS)
    assert Counter(row(q) for q in MAIN) == ROWS
    sub = Counter(q["subtype"] for q in MAIN if q["type"] != "unanswerable")
    assert sub == SUBTYPES
    assert Counter(q["wording"] for q in MAIN) == WORDING


def test_targets_come_from_the_dev_pool_only():
    for q in QUESTIONS:
        if q["type"] != "unanswerable":
            assert q["target"] in CTX.dev, q["id"]
        for m in g.DOTTED.findall(q["question"]):
            assert m not in CTX.test, (q["id"], m)


def test_d5_one_trace_and_one_impact_question_per_column():
    trace = Counter(q["target"] for q in MAIN if q["type"] == "trace")
    impact = Counter(q["target"] for q in MAIN if q["type"] == "impact")
    assert {c for c, n in trace.items() if n > 1} == g.D5_TRACE_EXCEPTIONS
    assert all(n == 1 for n in impact.values())


def test_every_trap_has_two_dev_questions():
    count = Counter(t for q in MAIN for t in q["traps"])
    nine = [
        "rename_chain", "select_star", "two_revenue_definitions", "deep_chain", "join_key_only",
        "fan_in_aggregate", "stale_doc", "near_duplicate_names", "exposures",
    ]  # fmt: skip
    assert all(count[t] >= 2 for t in nine), count


def test_gold_is_the_spec_computation():
    v = CTX.v
    for q in MAIN:
        gold, t = q["gold"], q["target"]
        if q["subtype"] in ("upstream", "multi_part", "ambiguous"):
            assert set(gold["upstream"]["direct"]) == gs.upstream(v, t, include_indirect=False)
            assert set(gold["upstream"]["all"]) == gs.upstream(v, t, include_indirect=True)
            assert gold["paths"] == [gs.longest_path(v, t, CTX.depths)]
        if q["subtype"] in ("computed", "false_premise"):
            assert gold["inputs"]["direct"] == [e["from"] for e in gs.direct_inputs(v, t)]
        if q["subtype"] == "downstream":
            assert set(gold["downstream"]["direct"]) == gs.downstream(v, t, include_indirect=False)
            assert set(gold["downstream"]["all"]) == gs.downstream(v, t, include_indirect=True)
        if q["subtype"] == "yesno":
            r = gold["reach"]
            for mode, ind in (("direct", False), ("all", True)):
                assert (r[mode] == "yes") == gs.reaches(v, r["from"], r["to"], include_indirect=ind)
        for e in gold.get("edges", []):
            assert (e["from"], e["to"]) in v.direct_pairs and e["line"] == CTX.lines[
                (e["from"], e["to"])
            ]


def test_existing_twenty_keep_id_text_target_and_expect():
    old = {json.loads(x)["id"]: json.loads(x) for x in g.V02.read_text().splitlines()}
    new = {q["id"]: q for q in MAIN if q["source"] == "v0.2"}
    assert set(new) == set(old) == {f"dev-{i:02d}" for i in range(1, 21)}
    for i, o in old.items():
        assert {k: new[i][k] for k in ("question", "target", "expect")} == {
            k: o[k] for k in ("question", "target", "expect")
        }
    assert {new[i]["subtype"] for i in ("dev-11", "dev-12", "dev-13")} == {"computed"}
    assert all(new[i]["type"] == "trace" for i in ("dev-11", "dev-12", "dev-13"))


def test_rfm_path_questions_are_worded_as_lineage():
    for q in MAIN:
        if q["subtype"] == "downstream" and q["source"] == "template":
            rfm = g.rfm_family(q["target"]) or any(
                g.rfm_family(c) for c in q["gold"]["downstream"]["all"]
            )
            assert ("in the lineage" in q["question"]) == rfm or q["wording"] == "paraphrase", q[
                "id"
            ]


def test_unanswerable_columns_do_not_exist_and_shipping_cost_is_the_near_miss():
    ids = CTX.v.model_columns | CTX.v.seed_columns
    un = [q for q in MAIN if q["type"] == "unanswerable"]
    assert all(q["target"] not in ids and q["gold"]["verdict"] == "refused" for q in un)
    assert "int_order_shipping.shipping_cost" in {q["target"] for q in un}
    assert "stg_shipments.shipping_cost" not in {q["target"] for q in un}


def test_paraphrase_slots_keep_their_template():
    for q in MAIN:
        if q["wording"] == "paraphrase" and q["source"] != "v0.2":
            assert q["template_question"] and "paraphrase_pending" in q["review_flags"]


def test_builder_on_the_test_pool_takes_only_test_columns():
    """D5b reuse: a Builder with split="test" draws trace and impact targets from the test pool."""
    b = g.Builder(g.load_ctx(), split="test", salt="unit-test:", next_id=1)
    assert b.pool == b.ctx.test
    assert b.fill_trace(g.Slot("trace", "upstream", "identifier", "2-3"))
    assert b.fill_impact(g.Slot("impact", "downstream", "identifier", "1"))
    assert b.fill_yesno(g.Slot("yesno", "yesno", "identifier", variant="no"))
    for q in b.questions:
        assert q["split"] == "test" and q["id"].startswith("test-")
        assert q["target"] in b.ctx.test and q["target"] not in b.ctx.dev
