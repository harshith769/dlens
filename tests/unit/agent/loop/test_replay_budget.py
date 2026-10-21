"""scripts/replay_answer_budget.py's tool-phase replay (s12-design v1.2, owner amendment 6): each
recorded tool-phase call is rebuilt with today's tool prompt and specs and measured."""

import sys
from pathlib import Path

from dlens.agent import prompts
from dlens.agent.llm.tokens import estimate_tokens
from dlens.agent.llm.types import Message
from dlens.agent.tools import Toolbox

sys.path.insert(0, str(Path(__file__).resolve().parents[4] / "scripts"))
import replay_answer_budget as replay  # noqa: E402

RECORD = {
    "question": "Where does fct.total come from?",
    "steps": [
        {
            "phase": "tool",
            "tool_calls": [{"id": "call_0", "name": "trace_upstream", "arguments": {}}],
            "results": [{"tool": "trace_upstream", "args": {"column_id": "fct.total"}}],
        },
        {"phase": "tool", "tool_calls": [], "results": []},
        {"phase": "answer", "tool_calls": [], "results": []},
    ],
}


def test_each_tool_phase_call_is_measured_with_its_history(box: Toolbox) -> None:
    calls = replay.tool_phase_tokens(RECORD, box)
    first = estimate_tokens(
        [
            Message(role="system", content=prompts.tool_system(box.has_docs)),
            Message(role="user", content=RECORD["question"]),
        ],
        box.specs(),
    )
    assert len(calls) == 2  # the answer step is not a tool-phase call
    assert calls[0] == (first, first)
    assert calls[1][0] > first  # the second call carries the trace result
