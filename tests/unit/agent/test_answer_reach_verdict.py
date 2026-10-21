"""ADR 0024: additive ``reach_verdict`` / ``reach_verdict_source`` on ``Answer``. Old records still
load. S4's answer prompt and draft schema are pinned: they changed once, in S12a (A1: S1's text
with one named substitution, and S1's schema), and any further change is a recorded decision."""

import hashlib
import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from dlens.agent import prompts
from dlens.agent.answer import DRAFT_SCHEMA, Answer, AnswerDraft

ROOT = Path(__file__).resolve().parents[3]

# sha256 after S12b B2 (the uncovered_parts line and schema property). Earlier: 1a35baaf… after
# B4 (the c_ phrase); 4d626b76… / 9f132d5e… after B3 (premise_corrected); 1bbca639… / 60364350…
# after S12a A1; 4bb98f41… / a945c5b8… at 776724f. A change here changes every S4 answer-phase
# cache key and is a recorded decision, never a side effect.
S4_ANSWER_SYSTEM = "627ab7179c2428a5ae11ee5482121211e51d301433a5644a40d76b28602ae548"
S4_DRAFT_SCHEMA = "4ff0f6df8f946f4e00f070b2a19f6ed4a56e6b11d0d77734114880060c44d90b"
S4_ANSWER_REPAIR = "cc417eb2aa5ab698cc0ed1052710865c4448b9b5e8feaab42ad8133b809bca9b"


def _sha(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()


def test_s4_answer_phase_is_unchanged() -> None:
    assert _sha(prompts.ANSWER_SYSTEM) == S4_ANSWER_SYSTEM
    assert _sha(json.dumps(DRAFT_SCHEMA, sort_keys=True)) == S4_DRAFT_SCHEMA
    assert _sha(prompts.ANSWER_REPAIR) == S4_ANSWER_REPAIR
    assert "reach_verdict" in AnswerDraft.model_fields  # S12a


def test_fields_default_to_null() -> None:
    a = Answer(answer_text="x")
    assert (a.reach_verdict, a.reach_verdict_source) == (None, None)


def test_round_trip() -> None:
    a = Answer(answer_text="No.", reach_verdict="no", reach_verdict_source="llm")
    assert Answer.model_validate_json(a.model_dump_json()) == a


@pytest.mark.parametrize(("verdict", "source"), [("maybe", "llm"), ("yes", "human"), (None, "llm")])
def test_invalid_values_are_rejected(verdict: str | None, source: str) -> None:
    with pytest.raises(ValidationError):
        Answer(answer_text="x", reach_verdict=verdict, reach_verdict_source=source)


def test_pre_adr_s4_shaped_answer_loads() -> None:
    old = {
        "answer_text": "It comes from raw_payments.amt.",
        "claims": [{"text": "t", "edge_ids": ["e_0123abcd"], "chunk_ids": []}],
        "subgraph": ["e_0123abcd"],
        "confidence": "high",
        "refused": False,
        "refusal_reason": None,
        "clarification": None,
        "partial_evidence": False,
        "citations": {
            "e_0123abcd": {"file": "m.sql", "line_start": 1, "line_end": 2, "level": "line"}
        },
        "validation_warning": False,
    }
    a = Answer.model_validate(old)
    # ADR 0025: an old claim loads with origin "model"
    want = {**old, "claims": [{**old["claims"][0], "origin": "model"}]}
    assert a.reach_verdict is None and a.model_dump(include=set(old)) == want
    assert a.premise_corrected is False


@pytest.mark.parametrize("variant", ["gold", "linked"])
def test_committed_s0_answers_still_load(variant: str) -> None:
    """S0 writes lean RunRecord-format dicts (S10: only what metrics reads), so the record itself
    is not a full ``RunRecord``; its ``final_answer`` must still be a valid ``Answer``."""
    path = ROOT / "eval" / "runs" / "s0" / f"s0-{variant}-dev.jsonl"
    n = 0
    for line in path.read_text().splitlines():
        rec = json.loads(line)
        a = Answer.model_validate(rec["final_answer"])
        assert a.reach_verdict is None  # S0's verdict stays record-level (structured.*)
        n += 1
    assert n == 84
