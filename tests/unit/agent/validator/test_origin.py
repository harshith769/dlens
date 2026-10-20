"""Claim ``origin`` and ``premise_corrected`` (s12-design B3, ADR 0025): labels only. The
validator sets ``repaired`` (R2r), ``completed`` (R8c, wins over repaired) and ``verdict``
(salvage's code claim); ``attach`` sets ``model`` and copies the LLM's ``premise_corrected``.
That no rule outcome moved is checked by the snapshot in conftest.py."""

import json

from dlens.agent.answer import AnswerDraft, DraftClaim, attach
from dlens.agent.tools import Toolbox
from dlens.agent.validator import salvage, validate

from .conftest import SNAPSHOT, answer, eid
from .test_verdict import fact

Q = "Where does fct_star.total come from?"


def _miscopy(real: str) -> str:
    return real[:-1] + ("0" if real[-1] != "0" else "1")


def test_attach_labels_model_and_copies_premise_corrected(traced: Toolbox):
    agg = eid(traced, "stg.amount", "fct.total")
    d = AnswerDraft(
        answer_text="t",
        claims=[DraftClaim(text="fct.total aggregates stg.amount", ids=[agg])],
        confidence="high",
        premise_corrected=True,
    )
    a = attach(d, traced)
    assert [c.origin for c in a.claims] == ["model"] and a.premise_corrected is True
    assert (
        attach(d.model_copy(update={"premise_corrected": False}), traced).premise_corrected is False
    )


def test_r2r_labels_repaired(traced: Toolbox):
    real = eid(traced, "stg.amount", "fct.total")
    r = validate(answer("t", ("fct.total aggregates stg.amount", [_miscopy(real)])), traced)
    assert r.passed and [c.origin for c in r.cleaned_answer.claims] == ["repaired"]


def test_a_prose_id_repair_labels_repaired(traced: Toolbox):
    real = eid(traced, "stg.amount", "fct.total")
    text = f"fct.total aggregates stg.amount ({_miscopy(real)})"
    r = validate(answer("t", (text, [real])), traced)
    assert r.repairs and r.cleaned_answer.claims[0].origin == "repaired"


def test_r8c_labels_completed(traced: Toolbox):
    last = eid(traced, "fct.total", "fct_star.total")
    r = validate(answer("t", ("fct_star.total comes from stg.amount", [last])), traced, Q)
    assert r.completions and r.cleaned_answer.claims[0].origin == "completed"


def test_completed_wins_over_repaired(traced: Toolbox):
    last = eid(traced, "fct.total", "fct_star.total")
    claim = ("fct_star.total comes from stg.amount", [_miscopy(last)])
    r = validate(answer("t", claim), traced, Q)
    assert r.repairs and r.completions
    assert r.cleaned_answer.claims[0].origin == "completed"


def test_untouched_claims_stay_model(traced: Toolbox):
    agg = eid(traced, "stg.amount", "fct.total")
    r = validate(answer("t", ("fct.total aggregates stg.amount", [agg])), traced)
    assert r.passed and [c.origin for c in r.cleaned_answer.claims] == ["model"]


def test_salvage_labels_code_verdict_claim_verdict(box: Toolbox):
    box.call("trace_upstream", {"column_id": "fct.total"})
    fact(box, "raw.id", "fct.total")
    agg = eid(box, "stg.amount", "fct.total")
    a = answer(
        "Yes, raw.id affects fct.total.", ("fct.total aggregates stg.amount", [agg]), verdict="yes"
    )
    out = salvage(validate(a, box), box)
    assert out is not None and out.claims[0].origin == "verdict"
    assert all(c.origin == "model" for c in out.claims[1:])


def test_code_never_sets_premise_corrected(box: Toolbox):
    box.call("trace_upstream", {"column_id": "fct.total"})
    fact(box, "raw.id", "fct.total")
    agg = eid(box, "stg.amount", "fct.total")
    a = answer("Yes, raw.id affects fct.total.", ("fct.total aggregates stg.amount", [agg]))
    r = validate(a, box)
    out = salvage(r, box)
    assert r.cleaned_answer.premise_corrected is False
    assert out is not None and out.premise_corrected is False


def test_the_snapshot_covers_the_pre_b3_tests() -> None:
    """106 pre-B3 tests, 81 validate / salvage calls, recorded before any B3 label existed."""
    data = json.loads(SNAPSHOT.read_text())
    assert len(data) == 106 and sum(len(v) for v in data.values()) == 81
