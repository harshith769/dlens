"""ADR 0027 (``uncovered_parts``, LLM-set) and ADR 0028 (``interpretation`` + source, code-set)."""

import json

from dlens.agent.answer import Answer, AnswerDraft, Interpretation, attach
from dlens.agent.loop import ask
from dlens.agent.tools import Toolbox

from .conftest import done, draft


def test_attach_copies_uncovered_parts_and_drops_blanks(box: Toolbox) -> None:
    d = AnswerDraft(answer_text="t", confidence="low", uncovered_parts=["who owns it", " ", ""])
    assert attach(d, box).uncovered_parts == ["who owns it"]


def test_code_sets_the_interpretation_with_source_code(box: Toolbox, make_client) -> None:
    client, _ = make_client([done(), draft()])
    run = ask("Where does raw.amount come from?", client, box)
    a = run.answer
    assert a.answer_text.startswith("Interpreted raw.amount as raw.amt.")
    assert a.interpretation == Interpretation(**{"from": "raw.amount", "to": "raw.amt"})
    assert a.interpretation_source == "code"
    final = run.record.final_answer or {}
    assert final["interpretation"] == {"from": "raw.amount", "to": "raw.amt"}
    assert "interpretation" not in AnswerDraft.model_fields  # the LLM never sets it


def test_no_interpretation_without_a_near_miss(box: Toolbox, make_client) -> None:
    client, _ = make_client([done(), draft()])
    a = ask("Where does raw.amt come from?", client, box).answer
    assert a.interpretation is None and a.interpretation_source is None


def test_old_answers_load_with_defaults() -> None:
    a = Answer.model_validate(json.loads('{"answer_text": "x"}'))
    assert (a.uncovered_parts, a.interpretation, a.interpretation_source) == ([], None, None)
    assert a.premise_corrected is False
