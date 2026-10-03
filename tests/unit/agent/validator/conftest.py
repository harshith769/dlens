"""Validator tests reuse the agent-loop fixtures: the hand-built shop on disk and its Toolbox."""

from __future__ import annotations

import pytest

from dlens.agent.answer import Answer, Claim
from dlens.agent.tools import Toolbox

from ..loop.conftest import box, logger, make_client, shop_root  # noqa: F401  (fixtures)


def eid(toolbox: Toolbox, src: str, dst: str) -> str:
    """The emitted id of the edge src -> dst (short ids, e.g. 'stg.amount')."""
    g = toolbox.graph
    for i in toolbox.emitted_ids:
        rec = toolbox.record(i) or {}
        if i.startswith("e_") and (g.display_name(rec["from"]), g.display_name(rec["to"])) == (
            src,
            dst,
        ):
            return i
    raise KeyError(f"{src} -> {dst} not emitted")


def answer(text: str, *claims: tuple[str, list[str]]) -> Answer:
    out = []
    for t, ids in claims:
        edges = [i for i in ids if i.startswith("e_")]
        out.append(Claim(text=t, edge_ids=edges, chunk_ids=[i for i in ids if i not in edges]))
    return Answer(answer_text=text, claims=out, confidence="high")


@pytest.fixture
def traced(request: pytest.FixtureRequest) -> Toolbox:
    """fct_star.total and fct_star.x_id traced, and fct's SQL around total fetched."""
    tb: Toolbox = request.getfixturevalue("box")
    tb.call("trace_upstream", {"column_id": "fct_star.total"})
    tb.call("trace_upstream", {"column_id": "fct_star.x_id"})
    tb.call("get_model_sql", {"model_id": "fct", "around_column": "total"})
    return tb
