import pytest
from pydantic import ValidationError

from dlens.agent.answer import DRAFT_SCHEMA, Answer, AnswerDraft, attach, render
from dlens.agent.tools import Toolbox


def test_draft_schema_matches_the_pydantic_model():
    fields = AnswerDraft.model_fields
    assert set(DRAFT_SCHEMA["properties"]) == set(fields)
    required = {n for n, f in fields.items() if f.is_required()}
    assert required <= set(DRAFT_SCHEMA["required"])
    claim = DRAFT_SCHEMA["properties"]["claims"]["items"]
    assert set(claim["properties"]) == {"text", "ids"}
    assert DRAFT_SCHEMA["properties"]["confidence"]["enum"] == ["high", "medium", "low"]
    assert "$ref" not in str(DRAFT_SCHEMA) and "$defs" not in str(DRAFT_SCHEMA)


def test_draft_rejects_extra_fields_and_bad_confidence():
    with pytest.raises(ValidationError):
        AnswerDraft.model_validate({"answer_text": "x", "confidence": "high", "file": "a.sql"})
    with pytest.raises(ValidationError):
        AnswerDraft.model_validate({"answer_text": "x", "confidence": "sure"})


def _traced(box: Toolbox) -> tuple[str, str]:
    r = box.call("trace_upstream", {"column_id": "fct.total"})
    e1, e2 = (line.split(":", 1)[0] for line in r.llm_payload["paths"][0])
    return e1, e2


def test_attach_splits_ids_and_takes_citations_from_the_ledger(box: Toolbox):
    e1, e2 = _traced(box)
    s = box.call("get_model_sql", {"model_id": "fct", "around_column": "total"})
    sid = s.llm_payload["windows"][0]["excerpt_id"]
    d = AnswerDraft(
        answer_text="total is sum(amount)",
        claims=[
            {"text": "total aggregates stg.amount", "ids": [e1, sid, e1]},
            {"text": "amount renames raw.amt", "ids": [e2, "e_deadbeef"]},
        ],
        confidence="medium",
    )
    a = attach(d, box)
    assert a.claims[0].edge_ids == [e1] and a.claims[0].chunk_ids == [sid]
    assert a.claims[1].edge_ids == [e2, "e_deadbeef"]
    assert a.subgraph == [e1, e2, "e_deadbeef"]
    assert set(a.citations) == {e1, e2, sid}  # the unknown id gets no citation
    for i, cite in a.citations.items():
        assert cite.model_dump() == box.record(i)["citation"]


def test_render_puts_file_line_markers_from_citations(box: Toolbox):
    e1, _ = _traced(box)
    a = attach(
        AnswerDraft(
            answer_text="t", claims=[{"text": "c", "ids": [e1, "e_deadbeef"]}], confidence="low"
        ),
        box,
    )
    out = render(a)
    assert "[models/fct.sql:3]" in out
    assert "[?e_deadbeef]" in out
    assert "Citations:" in out


def test_refusal_helper():
    a = Answer.refusal("no column matches")
    assert a.refused and a.refusal_reason == "no column matches" and not a.claims


def test_render_dedupes_identical_markers(box: Toolbox):
    e1, _ = _traced(box)
    a = attach(
        AnswerDraft(answer_text="t", claims=[{"text": "c", "ids": [e1]}], confidence="low"), box
    )
    a.claims[0].edge_ids.append("e_feedface")
    a.citations["e_feedface"] = a.citations[e1]
    claim_line = [ln for ln in render(a).splitlines() if ln.startswith("  - c")][0]
    assert claim_line.count("[models/fct.sql:3]") == 1
