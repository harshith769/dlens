from dlens.agent.answer import DRAFT_SCHEMA
from dlens.agent.llm.tokens import estimate_tokens
from dlens.agent.llm.types import Message
from dlens.agent.prompts import ANSWER_SYSTEM, TOOL_SYSTEM
from dlens.agent.tools import TOOL_SPECS


def test_tool_phase_fixed_cost_stays_small():
    """System prompt + the four specs ride on every tool-phase call (target <= ~900)."""
    assert estimate_tokens([Message(role="system", content=TOOL_SYSTEM)], TOOL_SPECS) <= 900


def test_answer_phase_fixed_cost_leaves_room_for_evidence():
    """591 est. after S12a; the two S4-only lines and schema properties of s12-design v1.2 add
    135 (726, measured and approved at S12b STOP 1). Any further growth is a recorded decision."""
    fixed = estimate_tokens([Message(role="system", content=ANSWER_SYSTEM)], None, DRAFT_SCHEMA)
    assert fixed <= 730
