"""eval/metrics.py against docs/plans/metrics-design.md v1.0 (S10).

Identity (gold as prediction is perfect), one hand-built case per decision, every M12 edge case,
the negation rule (Appendix B), the identifier filter (Appendix C), the citation guard (M7),
bootstrap determinism, and direct vs all on dev-70 / 72 / 73 / 74.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

import pytest

import metrics as M

ROOT = Path(__file__).parents[3]
CORPUS = ROOT / "corpora" / "synthetic_shop"
QUESTIONS = [json.loads(x) for x in (ROOT / "eval/questions/dev.jsonl").read_text().splitlines()]
BY_ID = {q["id"]: q for q in QUESTIONS}
INV, VIEW = M.load_inventory(CORPUS)

A, B, C = "stg_orders.order_id", "fct_orders.revenue_finance", "int_order_financials.sales_tax"


def sub(s: str) -> str:
    s = re.sub(r"\bA\b", A, s)
    s = re.sub(r"\bB\b", B, s)
    return re.sub(r"\bC\b", C, s)


def state(ex: M.Extraction, node: str) -> str:
    if node in ex.nodes("column", negated=True):
        return "neg"
    if node in ex.nodes("column", negated=False):
        return "kept"
    return "absent"


# ------------------------------------------------------------------ Appendix B (M3 rule 4)
APPENDIX_B = [
    ("It comes from A.", "kept", None, None),
    ("It does not come from A.", "neg", None, None),
    ("It doesn't use A.", "neg", None, None),
    ("It comes from A, not B.", "kept", "neg", None),
    ("It does not come from A; it comes from B.", "neg", "kept", None),
    ("It does not come from A, but from B.", "neg", "kept", None),
    ("It uses not only A but also B.", "kept", "kept", None),
    ("Every column except B is affected, including A.", "kept", "neg", None),
    ("All inputs are used except B.", None, "neg", None),
    ("A is used rather than B.", "kept", "neg", None),
    ("A is used instead of B.", "kept", "neg", None),
    ("Neither A nor B is used.", "neg", "neg", None),
    ("A no longer feeds B.", "neg", "neg", None),
    ("No, A does not reach B.", "neg", "neg", None),
    ("Yes, A reaches B in 3 hops.", "kept", "kept", None),
    ("It is computed without A.", "neg", None, None),
    ("B is affected. A is not used in the SQL.", "neg", "kept", None),
    ("A feeds B, which is not used by the dashboard.", "kept", "kept", None),
    ("A and B; neither is a direct input.", "kept", "kept", None),
    ("There is no direct edge from A to B.", "neg", "neg", None),
    ("A is not an input to B.", "neg", "neg", None),
    ("A isn't used.", "neg", None, None),
    ("A, which is not used by the dashboard, feeds B.", "kept", "kept", None),
    ("A is not aggregated directly; it reaches B through C.", "neg", "kept", "kept"),
    ("Only A, not B, is used.", "kept", "neg", None),
    ("The A column is not used.", "neg", None, None),
    ("A itself does not change.", "neg", None, None),
    ("A is never null.", "kept", None, None),
    ("Rows are kept where A is not null.", "kept", None, None),
    ("A is not null and feeds B.", "kept", "kept", None),
    ("A does not feed B when B is null.", "neg", "neg", None),
]


@pytest.mark.parametrize(("sentence", "a", "b", "c"), APPENDIX_B)
def test_appendix_b_negation(sentence: str, a: str | None, b: str | None, c: str | None) -> None:
    ex = M.extract(sub(sentence), INV)
    for node, want in ((A, a), (B, b), (C, c)):
        if want is not None:
            assert state(ex, node) == want, (sentence, node)


def test_appendix_b_has_at_least_15_rows() -> None:
    assert len(APPENDIX_B) >= 15


def test_curly_apostrophe_is_a_cue() -> None:
    assert state(M.extract(f"{A} isn’t used.", INV), A) == "neg"


# ------------------------------------------------------------------ Appendix C (M3 rule 1)
@pytest.mark.parametrize(
    ("text", "kind", "node"),
    [
        ("e.g. stg_orders.order_id is used", "column", "stg_orders.order_id"),
        ("see models/marts/fct_orders.sql", None, None),
        ("added in v0.3", None, None),
        ("github.com", None, None),
        ("Gemini 3.5", None, None),
        ("i.e. the finance revenue", None, None),
        ("fct_orders.revenue_net", "unknown", "fct_orders.revenue_net"),
        ("fct_returns.return_amount", "unknown", "fct_returns.return_amount"),
        ("model.synthetic_shop.fct_orders.order_id", "column", "fct_orders.order_id"),
        ("customers.customer_id", None, None),
        ("rfm_scores.rfm_score", "cte", "rfm_scores.rfm_score"),
        ("margins_monthly.margin_month", "cte", "margins_monthly.margin_month"),
        ("payroll.employee_salary", None, None),
    ],
)
def test_appendix_c_identifier_filter(text: str, kind: str | None, node: str | None) -> None:
    ex = M.extract(text, INV)
    dotted = [m for m in ex.mentions if m.kind in ("column", "unknown", "cte")]
    if kind is None:
        assert dotted == []
    else:
        assert [(m.kind, m.node) for m in dotted] == [(kind, node)]


def test_path_removes_bare_model_names_inside_it() -> None:
    assert M.extract("see models/marts/fct_orders.sql", INV).mentions == []
    assert M.extract("fct_orders is a mart", INV).nodes("model") == {"fct_orders"}


def test_exposure_names_with_spaces() -> None:
    ex = M.extract("It reaches the finance dashboard.", INV)
    assert ex.nodes("exposure") == {"finance_dashboard"}


def test_interpretation_lead_counts_b_not_a() -> None:
    text = "Interpreted stg_shipments.shipping_cost as stg_shipments.shipping_cost_usd. It feeds X."
    ex = M.extract(text, INV)
    assert ex.interpretations == [
        ("stg_shipments.shipping_cost", "stg_shipments.shipping_cost_usd")
    ]
    assert "stg_shipments.shipping_cost_usd" in ex.nodes("column")
    assert all(m.node != "stg_shipments.shipping_cost" for m in ex.mentions)


# --------------------------------------------------------------- relation names (M7, M8 a+)
def test_cast_alias_does_not_pass_the_guard() -> None:
    sql = "select cast(x as int) as amount from t"
    assert "amount" not in M.relation_names(sql)


def test_cte_and_qualified_derived_alias_pass_the_guard() -> None:
    sql = "with base as (select 1) select d.k from (select 1 as k) as d join base on true"
    assert M.relation_names(sql) == {"base", "d"}


def test_cte_list_holds_corpus_ctes_and_derived_aliases() -> None:
    assert {"rfm_scores", "order_agg", "margins_monthly", "revenue_monthly"} <= INV.ctes
    assert not INV.ctes & (INV.models | INV.seeds)


# ------------------------------------------------------------------------------ mode (M4)
def test_appendix_a_totals() -> None:
    modes = [M.primary_mode(q) for q in QUESTIONS]
    assert modes.count("direct") == 45 and modes.count("all") == 30


def test_cue_agrees_with_family_except_dev_50() -> None:
    clash = []
    for q in QUESTIONS:
        cue, mode = M.wording_cue(q["question"]), M.primary_mode(q)
        if mode and ((cue == "P" and mode == "all") or (cue == "E" and mode == "direct")):
            clash.append(q["id"])
    assert clash == ["dev-50"]


def test_composite_sizes() -> None:
    comp = [M.composite(q) for q in QUESTIONS]
    assert comp.count("trace") == 44 and comp.count("impact") == 24


def test_linker_test_flag_is_21_questions() -> None:
    flagged = M.linker_test_flagged(QUESTIONS, ROOT / "eval/linker/cases.jsonl")
    assert len(flagged) == 21 and {"dev-74", "dev-88", "dev-29"} <= flagged


# -------------------------------------------------------------------------- identity
def gold_prediction(q: dict[str, Any]) -> M.Prediction:
    """The gold answer written as prose, in the question's primary mode."""
    gold, subtype, mode = q["gold"], q["subtype"], M.primary_mode(q)
    if q["type"] == "unanswerable":
        return M.Prediction(kind="refused", answer_text="I can't answer this: no such column.")
    if subtype == "ambiguous" and gold["verdict"] == "clarify":
        return M.Prediction(kind="clarification", clarification=sorted(gold["candidates"]))
    lines: list[str] = []
    verdict = None
    assert mode is not None
    if subtype in ("upstream", "multi_part", "ambiguous"):
        cols = gold["upstream"][mode]
        lines.append(f"{q['target']} comes from {', '.join(cols)}.")
    elif subtype in ("computed", "false_premise"):
        cols = sorted(M.gold_set(gold, "inputs", mode))
        lines.append(f"It is computed from {', '.join(cols)}.")
        if subtype == "false_premise":
            lines.append(f"It does not use {gold['premise']['edge']['from']}.")
    elif subtype == "downstream":
        cols = gold["downstream"][mode]
        if cols:
            lines.append(f"Affected: {', '.join(cols)}.")
        if gold["exposures"][mode]:
            lines.append(f"Dashboards: {', '.join(gold['exposures'][mode])}.")
    elif subtype == "yesno":
        verdict = gold["reach"][mode]
        lines.append("Yes." if verdict == "yes" else "No.")
    return M.Prediction(kind="answered", answer_text=" ".join(lines), reach_verdict=verdict)


SCORED = [q for q in QUESTIONS if q["type"] != "ask"]
PERFECT_ONE = {
    "headline_f1",
    "upstream_f1",
    "inputs_f1",
    "inputs_f1_tolerant",
    "columns_f1",
    "models_f1",
    "exposures_f1",
    "yesno_correct",
    "refusal_correct",
    "chain_correct",
    "clarify_correct",
    "premise_rejected",
    "path_node_coverage",
    "fully_correct",
}
PERFECT_ZERO = {"false_refusal", "hallucination_rate", "has_hallucination"}


@pytest.mark.parametrize("q", SCORED, ids=[q["id"] for q in SCORED])
def test_identity_gold_as_prediction_is_perfect(q: dict[str, Any]) -> None:
    row = M.score_question(q, gold_prediction(q), INV, VIEW, CORPUS)
    for k, v in row["metrics"].items():
        if k in PERFECT_ONE:
            assert v == 1.0, (k, v)
        elif k in PERFECT_ZERO:
            assert v == 0.0, (k, v)


def test_identity_covers_every_headline() -> None:
    rows = [M.score_question(q, gold_prediction(q), INV, VIEW, CORPUS) for q in SCORED]
    with_f1 = [r for r in rows if "headline_f1" in r["metrics"]]
    assert len(with_f1) == 68
    assert all(
        r["metrics"]["fully_correct"] == 1.0 for r in rows if "fully_correct" in r["metrics"]
    )


# --------------------------------------------------------------- direct vs all (M4, M5)
def answered(text: str, verdict: str | None = None) -> M.Prediction:
    return M.Prediction(kind="answered", answer_text=text, reach_verdict=verdict)


def test_dev70_all_mode_set_and_empty_direct_gold() -> None:
    q = BY_ID["dev-70"]
    full = M.score_question(
        q,
        answered("Affected: " + ", ".join(q["gold"]["downstream"]["all"]) + "."),
        INV,
        VIEW,
        CORPUS,
    )
    assert full["mode"] == "all" and full["metrics"]["columns_f1"] == 1.0
    assert full["modes"]["columns_f1_direct"] == 0.0  # gold direct is empty, prediction is not
    empty = M.score_question(q, answered("Nothing is downstream."), INV, VIEW, CORPUS)
    assert empty["modes"]["columns_f1_direct"] == 1.0  # answered: empty vs empty = 1
    assert empty["metrics"]["columns_f1"] == 0.0


def test_dev74_verdict_depends_on_mode() -> None:
    q = BY_ID["dev-74"]
    yes = M.score_question(q, answered("Yes.", "yes"), INV, VIEW, CORPUS)
    assert yes["metrics"]["yesno_correct"] == 1.0
    assert yes["modes"]["yesno_direct"] == 0.0 and yes["modes"]["yesno_all"] == 1.0
    no = M.score_question(q, answered("No.", "no"), INV, VIEW, CORPUS)
    assert no["metrics"]["yesno_correct"] == 0.0


@pytest.mark.parametrize("qid", ["dev-72", "dev-73"])
def test_dev72_73_prose_yes_without_field_is_wrong(qid: str) -> None:
    q = BY_ID[qid]
    prose = M.score_question(q, answered("Yes, it does."), INV, VIEW, CORPUS)
    assert prose["metrics"]["yesno_correct"] == 0.0
    assert prose["diag"]["heuristic_verdict"] == "yes"  # labelled diagnostic only
    field = M.score_question(q, answered("It does.", "yes"), INV, VIEW, CORPUS)
    assert field["metrics"]["yesno_correct"] == 1.0


# ------------------------------------------------------------------------ M12 edge cases
@pytest.mark.parametrize("kind", ["refused", "missing", "crashed"])
def test_non_answer_on_answerable_scores_zero_even_with_empty_gold(kind: str) -> None:
    row = M.score_question(BY_ID["dev-70"], M.Prediction(kind=kind), INV, VIEW, CORPUS)
    assert row["modes"]["columns_f1_direct"] == 0.0
    assert row["metrics"]["columns_f1"] == 0.0
    assert row["metrics"]["false_refusal"] == float(kind == "refused")


def test_clarification_on_trace_question_scores_zero() -> None:
    row = M.score_question(
        BY_ID["dev-01"],
        M.Prediction(kind="clarification", clarification=["x.y"]),
        INV,
        VIEW,
        CORPUS,
    )
    assert row["metrics"]["upstream_f1"] == 0.0


def test_prf_edges() -> None:
    assert M.prf(set(), set()) == (1.0, 1.0, 1.0)
    assert M.prf({"a.b"}, set()) == (0.0, 0.0, 0.0)
    assert M.prf(set(), {"a.b"}) == (0.0, 0.0, 0.0)
    assert M.prf({"a.b", "c.d"}, {"a.b"})[2] == pytest.approx(2 / 3)


def record(question: str, **kw: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "question": question,
        "steps": [],
        "final_answer": {"answer_text": "x", "claims": [], "refused": False, "citations": {}},
        "tokens": {},
        "timings": {"total_ms": 1.0},
    }
    base.update(kw)
    return base


def test_join_fails_on_unmatched_and_duplicate() -> None:
    q = QUESTIONS[0]
    with pytest.raises(M.JoinError, match="unmatched"):
        M.join([record("not a dev question")], QUESTIONS)
    with pytest.raises(M.JoinError, match="duplicate"):
        M.join([record(q["question"]), record(q["question"])], QUESTIONS)


def test_missing_record_marks_run_incomplete() -> None:
    q = BY_ID["dev-01"]
    rec = record(
        q["question"],
        final_answer={
            "answer_text": "stg_payments.amount_usd comes from raw_payments.amt.",
            "claims": [],
            "refused": False,
            "citations": {},
        },
    )
    out = M.score_run([rec], [q, BY_ID["dev-02"]], corpus_dir=CORPUS)
    assert out["missing"] == ["dev-02"] and not out["complete"]
    by = {r["id"]: r for r in out["rows"]}
    assert by["dev-01"]["metrics"]["upstream_f1"] == 1.0
    assert by["dev-02"]["metrics"]["upstream_f1"] == 0.0


def test_truncated_payload_is_flagged_not_excused() -> None:
    rec = record(
        BY_ID["dev-01"]["question"],
        steps=[{"results": [{"llm_payload": {"truncated": True}, "side_records": {}}]}],
    )
    pred = M.from_record(rec)
    assert pred.truncated
    row = M.score_question(BY_ID["dev-01"], pred, INV, VIEW, CORPUS)
    assert row["truncated"] and row["metrics"]["upstream_f1"] == 0.0


# ------------------------------------------------------------------------------ M1 inputs
def test_closure_tolerant_vs_strict_inputs() -> None:
    q = BY_ID["dev-11"]  # computed: items_subtotal, refund_amount
    inputs = q["gold"]["inputs"]["direct"]
    deeper = sorted(
        M.norm(M.gs.upstream(VIEW, q["target"], include_indirect=False)) - M.norm(inputs)
    )
    text = f"It is computed from {', '.join(inputs)}, and {deeper[0]} further up."
    row = M.score_question(q, answered(text), INV, VIEW, CORPUS)
    assert row["metrics"]["inputs_f1_tolerant"] == 1.0
    assert row["metrics"]["inputs_f1"] < 1.0 == row["metrics"]["inputs_f1_tolerant"]
    assert row["metrics"]["headline_f1"] == row["metrics"]["inputs_f1"]  # strict is the headline


# ---------------------------------------------------------------------- M10 false premise
@pytest.mark.parametrize(
    ("text", "bucket"),
    [
        ("It does not include int_customer_order_history.sales_tax.", "rejected"),
        ("It uses int_customer_order_history.sales_tax.", "asserted"),
        ("It uses int_customer_order_history.items_subtotal.", "silent"),
    ],
)
def test_premise_case_o_buckets(text: str, bucket: str) -> None:
    row = M.score_question(BY_ID["dev-17"], answered(text), INV, VIEW, CORPUS)
    assert row["diag"]["premise_case"] == "O"
    assert row["diag"]["premise_bucket"] == bucket
    assert row["metrics"]["premise_rejected"] == float(bucket == "rejected")


def test_premise_case_u_has_two_buckets() -> None:
    q = BY_ID["dev-18"]
    ctx = M.score_question(
        q,
        answered("stg_payments.amount_usd reaches it through int_payment_events.event_amount_usd."),
        INV,
        VIEW,
        CORPUS,
    )
    assert ctx["diag"]["premise_case"] == "U" and ctx["diag"]["premise_bucket"] == "not_rejected"
    rej = M.score_question(
        q,
        answered("stg_payments.amount_usd is not aggregated directly into it."),
        INV,
        VIEW,
        CORPUS,
    )
    assert rej["diag"]["premise_bucket"] == "rejected"


def test_premise_corrected_field_counts_as_rejected() -> None:
    pred = answered("It uses int_customer_order_history.items_subtotal.")
    pred.premise_corrected = True
    row = M.score_question(BY_ID["dev-17"], pred, INV, VIEW, CORPUS)
    assert row["diag"]["premise_bucket"] == "rejected"


# ----------------------------------------------------------------------- M9 ambiguity
def test_chain_needs_target_as_non_negated_mention() -> None:
    q = BY_ID["dev-16"]
    ups = q["gold"]["upstream"]["direct"]
    good = M.score_question(
        q, answered(f"{q['target']} comes from {', '.join(ups)}."), INV, VIEW, CORPUS
    )
    assert good["metrics"]["chain_correct"] == 1.0 and good["metrics"]["upstream_f1"] == 1.0
    miss = M.score_question(q, answered(f"It comes from {', '.join(ups)}."), INV, VIEW, CORPUS)
    assert miss["metrics"]["chain_correct"] == 0.0 and miss["metrics"]["upstream_f1"] == 0.0


def test_clarify_candidates_superset() -> None:
    q = BY_ID["dev-46"]
    cands = q["gold"]["candidates"]
    ok = M.score_question(
        q, M.Prediction(kind="clarification", clarification=cands + ["x.y"]), INV, VIEW, CORPUS
    )
    assert ok["metrics"]["clarify_correct"] == 1.0
    part = M.score_question(
        q, M.Prediction(kind="clarification", clarification=cands[:1]), INV, VIEW, CORPUS
    )
    assert part["metrics"]["clarify_correct"] == 0.0
    ans = M.score_question(q, answered(f"{cands[0]} comes from somewhere."), INV, VIEW, CORPUS)
    assert ans["metrics"]["clarify_correct"] == 0.0


def test_refusal_and_false_refusal() -> None:
    assert (
        M.score_question(BY_ID["dev-92"], M.Prediction(kind="refused"), INV, VIEW, CORPUS)[
            "metrics"
        ]["refusal_correct"]
        == 1.0
    )
    assert (
        M.score_question(BY_ID["dev-92"], answered("It comes from x."), INV, VIEW, CORPUS)[
            "metrics"
        ]["refusal_correct"]
        == 0.0
    )


def test_interpretation_requires_lead_and_column() -> None:
    q = dict(BY_ID["dev-01"])
    q["gold"] = dict(q["gold"], interpretation={"text": "t", "column": "stg_payments.amount_usd"})
    lead = (
        "Interpreted stg_payments.amount as stg_payments.amount_usd."
        " It comes from raw_payments.amt."
    )
    assert M.score_question(q, answered(lead), INV, VIEW, CORPUS)["metrics"]["upstream_f1"] == 1.0
    plain = "It comes from raw_payments.amt."
    row = M.score_question(q, answered(plain), INV, VIEW, CORPUS)
    assert row["metrics"]["interpretation_correct"] == 0.0 and row["metrics"]["upstream_f1"] == 0.0


# ---------------------------------------------------------------------- M8 hallucination
def test_question_own_id_is_exempt_and_real_hallucination_counts() -> None:
    q = BY_ID["dev-92"]
    echo = M.score_question(
        q,
        M.Prediction(
            kind="refused", answer_text="fct_daily_revenue.revnue_finance does not exist."
        ),
        INV,
        VIEW,
        CORPUS,
    )
    assert echo["metrics"]["hallucination_rate"] == 0.0
    bad = M.score_question(
        BY_ID["dev-01"],
        answered("It comes from raw_payments.amt and raw_payments.amount_net."),
        INV,
        VIEW,
        CORPUS,
    )
    assert bad["metrics"]["hallucination_rate"] == 0.5
    assert bad["metrics"]["has_hallucination"] == 1.0
    assert bad["diag"]["hallucinated"] == ["raw_payments.amount_net"]


def test_cte_reference_is_neither_node_nor_hallucination() -> None:
    row = M.score_question(
        BY_ID["dev-01"],
        answered("It comes from raw_payments.amt via rfm_scores.rfm_score."),
        INV,
        VIEW,
        CORPUS,
    )
    assert row["cte_refs"] == 1 and "hallucination_rate" in row["metrics"]
    assert row["metrics"]["hallucination_rate"] == 0.0


# ------------------------------------------------------------------------ M7 citations
@pytest.fixture
def project(tmp_path: Path) -> Path:
    (tmp_path / "models").mkdir()
    (tmp_path / "models" / "m.sql").write_text(
        "select\n    a.x as total,\n    b.k\nfrom (select 1 as k) as sub\njoin t on t.k = sub.k\n"
    )
    (tmp_path / "models" / "j.sql").write_text("select {{ my_macro() }} from t\n")
    (tmp_path / "outside.sql").write_text("total\n")
    return tmp_path


def cit(file: str, a: int, b: int, level: str = "line") -> dict[str, Any]:
    return {"file": file, "line_start": a, "line_end": b, "level": level}


def edge(f: str, t: str, kind: str = "IDENTITY", key: str | None = None) -> M.EdgeInfo:
    return M.EdgeInfo(f, t, kind, key)


def test_direct_edge_needs_to_column(project: Path) -> None:
    e = edge("src.x", "m.total")
    assert M.check_citation("e_1", cit("models/m.sql", 2, 2), e, set(), project).valid
    assert not M.check_citation("e_1", cit("models/m.sql", 3, 3), e, set(), project).valid


def test_indirect_edge_needs_from_column(project: Path) -> None:
    e = edge("t.k", "m.total", "JOIN")
    assert M.check_citation("e_2", cit("models/m.sql", 5, 5), e, set(), project).valid
    assert not M.check_citation(
        "e_2", cit("models/m.sql", 2, 2), edge("t.zz", "m.total", "JOIN"), set(), project
    ).valid


def test_clause_key_on_derived_alias_passes_iv_k_plus(project: Path) -> None:
    e = edge("upstream.key_col", "m.total", "JOIN", key="sub.k")
    assert M.check_citation("e_3", cit("models/m.sql", 5, 5), e, set(), project).reason.startswith(
        "ok (clause key"
    )


def test_clause_key_on_cast_alias_fails_the_guard(tmp_path: Path) -> None:
    (tmp_path / "c.sql").write_text("select cast(x as int) as amount\nfrom t where amount > 0\n")
    e = edge("upstream.key_col", "c.y", "FILTER", key="amount.v")
    assert not M.check_citation("e_4", cit("c.sql", 2, 2), e, set(), tmp_path).valid


@pytest.mark.parametrize(
    ("c", "reason"),
    [
        (cit("models/m.sql", 0, 1), "line range out of bounds"),
        (cit("models/m.sql", 4, 99), "line range out of bounds"),
        (cit("../outside.sql", 1, 1), "file missing or outside the project"),
        (cit("models/nope.sql", 1, 1), "file missing or outside the project"),
        (cit("models/m.sql", 1, 5, "model"), "model-level citation"),
        (None, "no citation attached"),
    ],
)
def test_invalid_citations(project: Path, c: dict[str, Any] | None, reason: str) -> None:
    res = M.check_citation("e_5", c, edge("src.x", "m.total"), set(), project)
    assert not res.valid and res.reason == reason


def test_model_level_macro_bucket(project: Path) -> None:
    res = M.check_citation(
        "e_6", cit("models/j.sql", 1, 1, "model"), edge("t.a", "j.b"), set(), project
    )
    assert not res.valid and res.macro


def test_star_citation(tmp_path: Path) -> None:
    (tmp_path / "s.sql").write_text("select *\nfrom t\n")
    assert M.check_citation(
        "e_7", cit("s.sql", 1, 1, "star"), edge("t.a", "s.a"), set(), tmp_path
    ).valid
    assert not M.check_citation(
        "e_7", cit("s.sql", 2, 2, "star"), edge("t.a", "s.a"), set(), tmp_path
    ).valid


def test_answer_level_citations(project: Path) -> None:
    pred = M.Prediction(
        kind="answered",
        claims=[
            {"text": "m.total comes from src.x", "ids": ["e_1", "r_abc"]},
            {"text": "no ids", "ids": []},
        ],
        citations={"e_1": cit("models/m.sql", 2, 2)},
        edges={"e_1": edge("src.x", "m.total")},
        r3_failed={"e_1"},
        r3_checked={"e_1"},
    )
    c = M.score_citations(pred, INV, project)
    assert (c["checked"], c["valid"], c["r_facts"], c["claims_cited"], c["claims"]) == (
        1,
        1,
        1,
        1,
        2,
    )
    assert c["answer_valid"] is True
    assert c["r3_disagree"] == 1  # metrics says valid, the validator's R3 said invalid


def test_answered_answer_with_zero_citations_is_invalid(project: Path) -> None:
    pred = M.Prediction(kind="answered", claims=[{"text": "t", "ids": ["r_1"]}])
    assert M.score_citations(pred, INV, project)["answer_valid"] is False
    refused = M.Prediction(kind="refused")
    assert M.score_citations(refused, INV, project)["answer_valid"] is None


# ------------------------------------------------------------------------- adapters (M3)
def test_s4_views_raw_vs_validated() -> None:
    q = BY_ID["dev-01"]
    rec = record(
        q["question"],
        draft={
            "answer_text": "It comes from raw_payments.amt and raw_x.y.",
            "claims": [],
            "refused": False,
        },
        final_answer={
            "answer_text": "It comes from raw_payments.amt.",
            "claims": [{"text": "c", "edge_ids": ["e_1"], "chunk_ids": [], "origin": "augmented"}],
            "refused": False,
            "citations": {},
        },
    )
    raw, val, aug = (M.from_record(rec, v) for v in ("raw", "validated", "augmented"))
    assert "raw_x.y" in raw.answer_text and "raw_x.y" not in val.answer_text
    assert val.claims == [] and len(aug.claims) == 1


def test_reach_verdict_record_level_and_raw_view() -> None:
    q = BY_ID["dev-72"]
    rec = record(q["question"], structured={"reach_verdict": "yes"})
    assert M.from_record(rec).reach_verdict == "yes"
    rec2 = record(q["question"], draft={"answer_text": "Yes", "claims": [], "refused": False})
    rec2["final_answer"]["reach_verdict"] = {"value": "yes", "set_by": "code"}
    assert M.from_record(rec2, "validated").reach_verdict == "yes"
    assert M.from_record(rec2, "raw").reach_verdict is None


def test_adapter_kinds() -> None:
    q = BY_ID["dev-46"]
    clar = record(
        q["question"],
        final_answer={
            "answer_text": "",
            "claims": [],
            "refused": False,
            "clarification": {"question": "?", "candidates": ["a.b"]},
        },
    )
    assert M.from_record(clar).kind == "clarification"
    assert M.from_record(record(q["question"], final_answer=None)).kind == "crashed"
    ref = record(q["question"], final_answer={"answer_text": "no", "claims": [], "refused": True})
    assert M.from_record(ref).kind == "refused"


# ---------------------------------------------------------------------------- M13 stats
def test_bootstrap_is_deterministic_and_respects_min_cell() -> None:
    vals = [0.0, 0.5, 1.0, 1.0, 0.25, 0.75, 1.0, 0.0, 0.5, 1.0, 0.9]
    assert M.bootstrap_ci(vals) == M.bootstrap_ci(vals)
    lo, hi = M.bootstrap_ci(vals) or (None, None)
    assert lo is not None and hi is not None and lo <= M.mean(vals) <= hi
    assert M.bootstrap_ci(vals[:9]) is None
    assert M.bootstrap_ci(vals, seed=1) != M.bootstrap_ci(vals, seed=2)


def test_mcnemar_exact() -> None:
    a = {f"q{i}": False for i in range(5)}
    b = {f"q{i}": True for i in range(5)}
    assert M.mcnemar_exact(a, b) == {"b": 0, "c": 5, "p": 0.0625}
    assert M.mcnemar_exact(a, a)["p"] == 1.0


def test_paired_bootstrap() -> None:
    a = {f"q{i}": 0.0 for i in range(12)}
    b = {f"q{i}": 1.0 for i in range(12)}
    out = M.paired_bootstrap(a, b)
    assert out["n"] == 12 and out["diff"] == 1.0 and out["ci"] == (1.0, 1.0)


def test_percentile_nearest_rank() -> None:
    assert M.percentile([5.0, 1.0, 3.0, 2.0, 4.0], 50) == 3.0
    assert M.percentile(list(map(float, range(1, 101))), 95) == 95.0
    assert M.percentile([], 50) is None


def test_clarify_question_has_no_path_metric() -> None:
    """Metric bug found by the identity test: dev-46's gold carries a path, but its correct
    answer is a clarification (metrics-design change log, 19 Oct 2026)."""
    q = BY_ID["dev-46"]
    assert q["gold"].get("paths")
    pred = M.Prediction(kind="clarification", clarification=q["gold"]["candidates"])
    assert "path_node_coverage" not in M.score_question(q, pred, INV, VIEW, CORPUS)["metrics"]


def test_metrics_never_imports_the_system_under_test() -> None:
    source = (ROOT / "eval" / "metrics.py").read_text()
    imports = re.findall(r"^\s*(?:from|import)\s+([\w.]+)", source, re.M)
    banned = ("dlens.lineage", "dlens.agent", "dlens.retrieval", "dlens.graph")
    assert not [i for i in imports if i.startswith(banned)]
    assert "dlens.gold_spec" in source or "from dlens import gold_spec" in source


def test_valid_star_citation_is_not_listed_as_invalid(tmp_path: Path) -> None:
    """Reporting bug found on the S0 run: a valid star citation was listed under the answer's
    invalid reasons (metrics-design change log, 19 Oct 2026)."""
    (tmp_path / "s.sql").write_text("select *\nfrom t\n")
    pred = M.Prediction(
        kind="answered",
        claims=[{"text": "s.a comes from t.a", "ids": ["e_1"]}],
        citations={"e_1": cit("s.sql", 1, 1, "star")},
        edges={"e_1": edge("t.a", "s.a")},
    )
    c = M.score_citations(pred, INV, tmp_path)
    assert c["valid"] == 1 and c["invalid"] == {}


# ------------------------------------------------------------------------- v1.1 (owner)
def test_no_verdict_with_zero_file_citations_is_na(project: Path) -> None:
    """M7 v1.1: the system's own "no" with nothing to cite is n/a, never invalid."""
    pred = M.Prediction(kind="answered", answer_text="No.", reach_verdict="no", claims=[])
    assert M.score_citations(pred, INV, project)["answer_valid"] is None
    only_fact = M.Prediction(
        kind="answered", reach_verdict="no", claims=[{"text": "t", "ids": ["r_1"]}]
    )
    assert M.score_citations(only_fact, INV, project)["answer_valid"] is None


def test_no_verdict_with_a_bad_citation_is_still_invalid(project: Path) -> None:
    pred = M.Prediction(
        kind="answered",
        reach_verdict="no",
        claims=[{"text": "m.total comes from src.x", "ids": ["e_1"]}],
        citations={"e_1": cit("models/m.sql", 3, 3)},
        edges={"e_1": edge("src.x", "m.total")},
    )
    assert M.score_citations(pred, INV, project)["answer_valid"] is False


def test_yes_or_missing_verdict_with_zero_citations_stays_invalid(project: Path) -> None:
    for verdict in ("yes", None):
        pred = M.Prediction(kind="answered", reach_verdict=verdict, claims=[])
        assert M.score_citations(pred, INV, project)["answer_valid"] is False


def test_na_uses_the_system_verdict_not_the_gold() -> None:
    q = BY_ID["dev-10"]  # gold "no"
    assert q["gold"]["reach"]["all"] == "no"
    wrong_yes = M.score_question(q, answered("Yes.", "yes"), INV, VIEW, CORPUS)
    assert wrong_yes["metrics"]["citation_valid_answer"] == 0.0
    said_no = M.score_question(q, answered("No.", "no"), INV, VIEW, CORPUS)
    assert "citation_valid_answer" not in said_no["metrics"]


def test_clarify_question_answered_for_every_candidate_is_correct() -> None:
    q = BY_ID["dev-46"]
    cands = q["gold"]["candidates"]
    both = " ".join(f"{c} comes from fct_orders.order_date." for c in cands)
    assert (
        M.score_question(q, answered(both), INV, VIEW, CORPUS)["metrics"]["clarify_correct"] == 1.0
    )


def test_per_candidate_answer_missing_one_candidate_is_wrong() -> None:
    q = BY_ID["dev-46"]
    c0, c1 = q["gold"]["candidates"][:2]
    one = f"{c0} comes from fct_orders.order_date."
    assert (
        M.score_question(q, answered(one), INV, VIEW, CORPUS)["metrics"]["clarify_correct"] == 0.0
    )
    negated = f"{c0} comes from fct_orders.order_date. It is not {c1}."
    row = M.score_question(q, answered(negated), INV, VIEW, CORPUS)
    assert row["metrics"]["clarify_correct"] == 0.0


def test_r3_disagreement_counts_only_ids_r3_ran_on(project: Path) -> None:
    """Found in Step 5 (diagnostic only): a miscopied id fails R2 and never reaches R3."""
    pred = M.Prediction(
        kind="answered",
        claims=[{"text": "m.total comes from src.x", "ids": ["e_1", "e_bad"]}],
        citations={"e_1": cit("models/m.sql", 2, 2)},
        edges={"e_1": edge("src.x", "m.total")},
        r3_checked={"e_1"},
    )
    c = M.score_citations(pred, INV, project)
    assert c["checked"] == 2 and c["valid"] == 1  # e_bad: no citation attached, invalid
    assert c["r3_disagree"] == 0  # e_1 agrees (valid, R3 passed); e_bad was never R3-checked


def test_r3_checked_from_record() -> None:
    rec = record(
        BY_ID["dev-01"]["question"],
        evidence={"ids": ["e_1"]},
        validation={"skipped": False, "first": {"failures": []}},
    )
    assert M.from_record(rec).r3_checked == {"e_1"}
    assert M.from_record(record(BY_ID["dev-01"]["question"])).r3_checked == set()
