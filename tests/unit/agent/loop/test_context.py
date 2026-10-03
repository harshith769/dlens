import re

from dlens.agent.context import History, digest, fit
from dlens.agent.llm.types import Message
from dlens.agent.tools import TOOL_SPECS, Toolbox
from dlens.agent.tools.budget import payload_json

ID = re.compile(r"\b[es]_[0-9a-f]{8}\b")


def _results(box: Toolbox):
    return [
        box.call("trace_upstream", {"column_id": "fct_star.total"}),
        box.call("impact_downstream", {"column_id": "raw.amt"}),
        box.call("get_model_sql", {"model_id": "fct"}),
        box.call("resolve_entity", {"text": "x_id"}),
        box.call("trace_upstream", {"column_id": "nope.x"}),
    ]


def test_digests_keep_every_id_at_both_levels(box: Toolbox):
    for r in _results(box):
        original = set(ID.findall(r.content))
        for level in (1, 2):
            d = payload_json(digest(r, level))
            assert original <= set(ID.findall(d)), (r.tool, level)
    sql = _results(box)[2]
    d1 = digest(sql, 1)
    assert "excerpt" not in d1 and d1["windows"] == sql.llm_payload["windows"]


def test_level_two_drops_expressions(box: Toolbox):
    r = box.call("trace_upstream", {"column_id": "fct.total"})
    assert any("sum(amount)" in line for line in digest(r, 1)["edges"])
    assert not any("sum(amount)" in line for line in digest(r, 2)["edges"])


def test_fit_compacts_oldest_first_and_logs(box: Toolbox):
    h = History([Message(role="system", content="s"), Message(role="user", content="q")])
    ids: set[str] = set()
    for i, r in enumerate(_results(box)[:3]):
        h.add_tool(r, f"call_{i}")
        ids |= set(ID.findall(r.content))
    full = h.tokens(TOOL_SPECS)
    ok, log = fit(h, TOOL_SPECS, full - 5, step=3)
    assert ok and log and log[0]["message_index"] == 2 and log[0]["level"] == 1
    assert {"step", "message_index", "tool", "level", "tokens_before", "tokens_after"} <= set(
        log[0]
    )
    ok, log = fit(h, TOOL_SPECS, 10, step=4)  # impossible: report it, still keep ids
    assert not ok
    kept = set(ID.findall(" ".join(m.content for m in h.messages)))
    assert ids <= kept
