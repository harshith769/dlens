"""One section per rule, including the spec §8 adversarial cases (fake ids, wrong lines)."""

from pathlib import Path

from dlens.agent.tools import Toolbox
from dlens.agent.validator import (
    ValidationContext,
    repair_candidates,
    rule_cites,
    rule_kind_consistency,
    rule_known_nodes,
    rule_on_disk,
    rule_prose_refs,
    rule_relevance,
    validate,
    within_one_edit,
)

from ..loop.conftest import make_chain_shop
from .conftest import answer, eid


def rules(result) -> list[str]:
    return sorted(f.rule for f in result.failures)


def sql_id(box: Toolbox) -> str:
    return next(i for i in box.emitted_ids if i.startswith("s_"))


# -- a clean answer passes (no false positives on the happy path) ------------------------------


def test_a_clean_answer_passes(traced: Toolbox):
    agg = eid(traced, "stg.amount", "fct.total")
    ren = eid(traced, "raw.amt", "stg.amount")
    star = eid(traced, "fct.total", "fct_star.total")
    a = answer(
        "fct_star.total passes fct.total through; fct.total is computed on line 3 of "
        "models/fct.sql by aggregating stg.amount, which renames raw.amt.",
        ("fct_star.total is the same value as fct.total", [star]),
        ("fct.total aggregates stg.amount on line 3", [agg, sql_id(traced)]),
        ("stg.amount renames raw.amt", [ren]),
    )
    r = validate(a, traced, "Where does fct_star.total come from?")
    assert r.passed, r.failures
    assert not r.repairs and r.counts == {}


# -- R1 ----------------------------------------------------------------------------------------


def test_r1_claim_without_ids(traced: Toolbox):
    a = answer("x", ("fct.total is a sum", []))
    assert [f.rule for f in rule_cites(a, ValidationContext.build(traced))] == ["R1"]


# -- R2 / R2r ----------------------------------------------------------------------------------


def test_r2_fake_id(traced: Toolbox):
    r = validate(answer("t", ("fct.total aggregates stg.amount", ["e_deadbeef"])), traced)
    assert "R2" in rules(r) and not r.repairs


def test_r2_id_from_a_previous_question(box: Toolbox):
    box.call("trace_upstream", {"column_id": "fct.total"})
    old = eid(box, "stg.amount", "fct.total")
    box.reset()
    box.call("trace_upstream", {"column_id": "stg.x_id"})
    r = validate(answer("t", ("fct.total aggregates stg.amount", [old])), box)
    assert "R2" in rules(r) and not r.repairs


def test_r2_wrong_prefix_is_never_repaired(traced: Toolbox):
    real = eid(traced, "stg.amount", "fct.total")
    wrong = "s_" + real[2:]
    assert repair_candidates(wrong, traced.emitted_ids) == []
    r = validate(answer("t", ("fct.total aggregates stg.amount", [wrong])), traced)
    assert "R2" in rules(r) and not r.repairs


def test_r2r_one_char_miscopy_is_repaired(traced: Toolbox):
    real = eid(traced, "stg.amount", "fct.total")
    bad = real[:-1] + ("0" if real[-1] != "0" else "1")
    r = validate(answer("t", ("fct.total aggregates stg.amount", [bad])), traced)
    assert r.passed, r.failures
    assert r.repairs == [{"claim_index": 0, "from": bad, "to": real}]
    assert r.cleaned_answer.claims[0].edge_ids == [real]
    assert real in r.cleaned_answer.citations


def test_r2r_seven_hex_prefix_is_repaired(traced: Toolbox):
    sid = sql_id(traced)
    r = validate(answer("t", ("fct.total is computed here", [sid[:-1]])), traced)
    assert r.repairs == [{"claim_index": 0, "from": sid[:-1], "to": sid}]
    assert r.passed, r.failures


def test_r2r_ambiguous_miscopy_is_not_repaired(traced: Toolbox):
    rec = traced.record(eid(traced, "stg.amount", "fct.total"))
    traced._emitted["e_aaaaaaa1"] = rec  # crafted: two emitted ids one edit from the bad one
    traced._emitted["e_aaaaaaa2"] = rec
    assert len(repair_candidates("e_aaaaaaa3", traced.emitted_ids)) == 2
    r = validate(answer("t", ("fct.total aggregates stg.amount", ["e_aaaaaaa3"])), traced)
    assert "R2" in rules(r) and not r.repairs
    assert "ambiguous" in next(f.message for f in r.failures if f.rule == "R2")


def test_within_one_edit():
    assert within_one_edit("e_12345678", "e_12345679")  # substitution
    assert within_one_edit("e_1234567", "e_12345678")  # insertion
    assert within_one_edit("e_4b2_403a", "e_4b2c403a")
    assert not within_one_edit("e_12345678", "e_12345690")


# -- R3 ----------------------------------------------------------------------------------------


def _r3(box: Toolbox, item: str):
    a = answer("t", ("claim", [item]))
    return rule_on_disk(a, ValidationContext.build(box))


def test_r3_range_past_eof(traced: Toolbox):
    i = eid(traced, "stg.amount", "fct.total")
    traced.record(i)["citation"].update(line_start=90, line_end=99)
    assert "outside" in _r3(traced, i)[0].message


def test_r3_range_not_containing_the_column(traced: Toolbox):
    i = eid(traced, "raw.amt", "stg.amount")
    traced.record(i)["citation"].update(line_start=1, line_end=1)  # "select"
    assert "does not contain 'amount'" in _r3(traced, i)[0].message


def test_r3_path_traversal(traced: Toolbox, shop_root: Path):
    (shop_root.parent / "secret.sql").write_text("select amount as total")
    i = eid(traced, "stg.amount", "fct.total")
    traced.record(i)["citation"].update(file="../secret.sql", line_start=1, line_end=1)
    assert "outside the project" in _r3(traced, i)[0].message


def test_r3_file_edited_after_ingest(traced: Toolbox, shop_root: Path):
    edge, sid = eid(traced, "stg.amount", "fct.total"), sql_id(traced)
    assert not _r3(traced, edge) and not _r3(traced, sid)
    fct = shop_root / "models/fct.sql"
    fct.write_text(fct.read_text().replace("as total", "as grand_total"))
    assert "does not contain 'total'" in _r3(traced, edge)[0].message
    assert "changed since" in _r3(traced, sid)[0].message


def test_r3_star_and_seed_levels(traced: Toolbox):
    star = eid(traced, "fct.total", "fct_star.total")
    assert traced.record(star)["citation"]["level"] == "star" and not _r3(traced, star)
    traced.record(star)["citation"].update(file="models/stg.sql", line_start=1, line_end=1)
    assert "'*'" in _r3(traced, star)[0].message


# -- R4 ----------------------------------------------------------------------------------------


def _r4(box: Toolbox, a, q: str = ""):
    return [(f.rule, f.item_id) for f in rule_known_nodes(a, ValidationContext.build(box, q))]


def test_r4_invented_column_is_hallucinated(traced: Toolbox):
    a = answer("fct.discount_pct comes from stg.amount.")
    assert _r4(traced, a) == [("R4.hallucinated", "fct.discount_pct")]


def test_r4_real_column_not_in_evidence_is_unsupported(box: Toolbox):
    box.call("trace_upstream", {"column_id": "fct.total"})
    a = answer("t", ("fct.total also feeds stg.x_id", [eid(box, "stg.amount", "fct.total")]))
    assert _r4(box, a) == [("R4.unsupported", "stg.x_id")]
    assert _r4(box, a, q="Is stg.x_id related to fct.total?") == []  # named by the question


def test_r4_false_premise_question_does_not_exempt_a_hallucination(traced: Toolbox):
    q = "Why does fct.discount_pct depend on stg.amount?"
    a = answer(
        "fct.discount_pct depends on stg.amount.",
        ("fct.discount_pct aggregates stg.amount", [eid(traced, "stg.amount", "fct.total")]),
    )
    r = validate(a, traced, q)
    assert ("R4.hallucinated", "fct.discount_pct") in [(f.rule, f.item_id) for f in r.failures]
    assert not r.passed


def test_r4_ignores_paths_and_abbreviations(traced: Toolbox):
    a = answer("See models/fct.sql and stg.sql, e.g. line 3.")
    assert _r4(traced, a) == []


def test_r4_identifiers_shown_in_sql_excerpts_are_evidence(box: Toolbox, shop_root: Path):
    (shop_root / "models/fct.sql").write_text(
        "-- totals\nselect\n    sum(t_agg.amount) as total,\n    x_id\nfrom t_agg\ngroup by x_id\n"
    )
    box.call("get_model_sql", {"model_id": "fct", "around_column": "total"})
    assert _r4(box, answer("fct reads t_agg.amount")) == []


# -- R5 ----------------------------------------------------------------------------------------


def _r5(box: Toolbox, a):
    return [f.item_id for f in rule_kind_consistency(a, ValidationContext.build(box))]


def test_r5_aggregated_claim_citing_an_identity_edge(traced: Toolbox):
    ident = eid(traced, "stg.x_id", "fct.x_id")
    assert _r5(traced, answer("t", ("fct.x_id is aggregated from stg.x_id", [ident]))) == [
        "aggregated"
    ]


def test_r5_matching_kinds_pass(traced: Toolbox):
    ren = eid(traced, "raw.amt", "stg.amount")
    agg = eid(traced, "stg.amount", "fct.total")
    a = answer(
        "t",
        ("stg.amount renames raw.amt", [ren]),
        ("fct.total is the sum of stg.amount", [agg]),
        ("in the same model, x_id is kept", [eid(traced, "stg.x_id", "fct.x_id")]),
    )
    assert _r5(traced, a) == []


def test_r5_skips_claims_citing_only_excerpts(traced: Toolbox):
    assert _r5(traced, answer("t", ("total is renamed here", [sql_id(traced)]))) == []


# -- R7 ----------------------------------------------------------------------------------------


def _r7(box: Toolbox, a):
    return [f.rule for f in rule_relevance(a, ValidationContext.build(box))]


def test_r7_real_edge_cited_for_an_unrelated_claim(traced: Toolbox):
    unrelated = eid(traced, "raw.id", "stg.x_id")
    assert _r7(traced, answer("t", ("fct.total comes from stg.amount", [unrelated]))) == ["R7"]


def test_r7_a_repair_cannot_launder_an_unrelated_id(traced: Toolbox):
    unrelated = eid(traced, "raw.id", "stg.x_id")
    bad = unrelated[:-1] + ("0" if unrelated[-1] != "0" else "1")
    r = validate(answer("t", ("fct.total comes from stg.amount", [bad])), traced)
    assert r.repairs and r.repairs[0]["to"] == unrelated
    assert "R7" in rules(r) and not r.passed


def test_r7_model_level_mention_touches_an_edge_out_of_that_model(shop_root: Path):
    box = Toolbox(make_chain_shop(), shop_root)
    box.call("trace_upstream", {"column_id": "r_hist.refund_amount"})
    e = eid(box, "r_raw.refund_amt", "r_stg.refund_amt")
    assert _r7(box, answer("t", ("the refund amount is loaded from r_raw", [e]))) == []
    assert _r7(box, answer("t", ("the refund amount is read by r_hist", [e]))) == ["R7"]


def test_r7_does_not_double_count_ids_that_failed_r2(traced: Toolbox):
    r = validate(answer("t", ("fct.total comes from stg.amount", ["e_deadbeef"])), traced)
    assert r.counts == {"R2": 1}


def test_r7_excerpt_touches_its_model_and_entity_free_claims_are_exempt(traced: Toolbox):
    assert _r7(traced, answer("t", ("fct.total is computed here", [sql_id(traced)]))) == []
    other = eid(traced, "raw.id", "stg.x_id")
    assert _r7(traced, answer("t", ("the value is renamed", [other]))) == []


# -- R6 ----------------------------------------------------------------------------------------


def _r6(box: Toolbox, a):
    return [f.item_id for f in rule_prose_refs(a, ValidationContext.build(box))]


def test_r6_line_not_covered_by_any_citation(traced: Toolbox):
    agg = eid(traced, "stg.amount", "fct.total")
    assert _r6(traced, answer("t", ("fct.total is defined at line 99", [agg]))) == ["line 99"]


def test_r6_covered_line_and_matching_path_pass(traced: Toolbox):
    agg = eid(traced, "stg.amount", "fct.total")
    a = answer("fct.total is on line 3 of models/fct.sql.", ("fct.sql line 3 sums amount", [agg]))
    assert _r6(traced, a) == []


def test_r6_path_without_a_citation_in_that_file(traced: Toolbox):
    agg = eid(traced, "stg.amount", "fct.total")
    assert _r6(traced, answer("see models/other.sql", ("fct.total sums", [agg]))) == [
        "models/other.sql"
    ]


def test_r6_claim_is_checked_against_its_own_citations(traced: Toolbox):
    ren = eid(traced, "raw.amt", "stg.amount")  # models/stg.sql line 3
    assert _r6(traced, answer("t", ("renamed in models/fct.sql", [ren]))) == ["models/fct.sql"]


# -- skipped answers ---------------------------------------------------------------------------


def test_refused_and_clarification_answers_are_skipped(traced: Toolbox):
    from dlens.agent.answer import Answer, Clarification

    for a in (
        Answer.refusal("no column matches fct.discount_pct"),
        Answer(answer_text="which?", clarification=Clarification(question="?", candidates=[])),
    ):
        r = validate(a, traced)
        assert r.passed and r.skipped


# -- R8 ----------------------------------------------------------------------------------------


def _r8(box: Toolbox, a):
    from dlens.agent.validator import rule_connectivity

    return [f.rule for f in rule_connectivity(a, ValidationContext.build(box))]


def test_r8_skipped_hop_fails_and_the_full_chain_passes(traced: Toolbox):
    # like g: "fct_star.total comes from stg.amount" citing only the last hop
    last = eid(traced, "fct.total", "fct_star.total")
    agg = eid(traced, "stg.amount", "fct.total")
    claim = "fct_star.total comes from stg.amount"
    assert _r8(traced, answer("t", (claim, [last]))) == ["R8"]
    assert _r8(traced, answer("t", (claim, [agg, last]))) == []


def test_r8_false_premise_direct_claim(traced: Toolbox):
    last = eid(traced, "fct.total", "fct_star.total")
    assert _r8(traced, answer("t", ("fct_star.total comes directly from raw.amt", [last]))) == [
        "R8"
    ]


def test_r8_two_inputs_feeding_one_column(shop_root: Path):
    from dlens.lineage import Edge, EdgeKind

    from ..loop.conftest import P, _extend
    from ..tools.conftest import make_shop

    extra = Edge(
        from_column=f"{P}.stg.x_id",
        to_column=f"{P}.fct.total",
        kind=EdgeKind.TRANSFORMATION,
        expression="sum(amount) + x_id",
        file="models/fct.sql",
        lines=(3, 3),
    )
    box = Toolbox(_extend(make_shop(), {}, {}, [extra]), shop_root)
    box.call("trace_upstream", {"column_id": "fct.total"})
    a_in, b_in = eid(box, "stg.amount", "fct.total"), eid(box, "stg.x_id", "fct.total")
    claim = "stg.amount and stg.x_id both feed fct.total"
    assert _r8(box, answer("t", (claim, [a_in, b_in]))) == []
    assert _r8(box, answer("t", (claim, [a_in]))) == ["R8"]


def test_r8_exemptions(traced: Toolbox):
    agg = eid(traced, "stg.amount", "fct.total")
    assert _r8(traced, answer("fct_star.total comes from raw.amt", ("fct.total sums", [agg]))) == []
    assert _r8(traced, answer("t", ("fct.total comes from stg.amount", ["e_deadbeef"]))) == []


# -- R2 on ids written in prose ----------------------------------------------------------------


def test_r2_prose_ids_must_be_in_the_ledger(traced: Toolbox):
    agg = eid(traced, "stg.amount", "fct.total")
    ok = answer(
        f"fct.total aggregates stg.amount ({agg}).", ("fct.total aggregates stg.amount", [agg])
    )
    assert validate(ok, traced).passed
    bad = answer("t", ("fct.total aggregates stg.amount (e_deadbeef)", [agg]))
    r = validate(bad, traced)
    assert [(f.rule, f.claim_index, f.item_id) for f in r.failures] == [("R2", 0, "e_deadbeef")]


def test_r2_prose_id_miscopy_is_repaired_and_rewritten(traced: Toolbox):
    agg = eid(traced, "stg.amount", "fct.total")
    bad = agg[:-1] + ("0" if agg[-1] != "0" else "1")
    a = answer(
        f"fct.total aggregates stg.amount ({bad}).", ("fct.total aggregates stg.amount", [agg])
    )
    r = validate(a, traced)
    assert r.passed, r.failures
    assert {"claim_index": None, "from": bad, "to": agg, "in": "text"} in r.repairs
    assert agg in r.cleaned_answer.answer_text and bad not in r.cleaned_answer.answer_text
    assert bad in a.answer_text  # the input answer is untouched
