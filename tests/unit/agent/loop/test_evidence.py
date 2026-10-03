from dlens.agent.evidence import ID_RE, build_evidence, render_evidence, tool_errors, trim
from dlens.agent.tools import Toolbox


def test_only_emitted_ids_and_distance_priorities(box: Toolbox):
    box.call("trace_upstream", {"column_id": "fct_star.total"})
    box.call("get_model_sql", {"model_id": "fct", "around_column": "total"})
    box.call("trace_upstream", {"column_id": "nope.nothing"})  # error: not evidence
    items = build_evidence(box)
    ids = [it.id for it in items if it.id]
    assert set(ids) == set(box.emitted_ids)
    assert set(ID_RE.findall(render_evidence(items))) <= box.emitted_ids
    prio = {it.id: it.priority for it in items if it.id}
    edges = [i for i in ids if i.startswith("e_")]
    assert sorted(prio[e] for e in edges) == [1, 2, 3]
    assert all(prio[i] == 0 for i in ids if i.startswith("s_"))
    assert tool_errors(box) and "unknown_column" in tool_errors(box)[0]


def test_impact_edges_and_context_line(box: Toolbox):
    box.call("impact_downstream", {"column_id": "raw.amt"})
    text = render_evidence(build_evidence(box))
    assert "impact of raw.amt" in text and "dash (dashboard)" in text
    assert set(ID_RE.findall(text)) == box.emitted_ids


def test_resolve_candidates_only_when_ambiguous_or_nothing_citable(box: Toolbox):
    box.call("resolve_entity", {"text": "fct.total"})  # exact, not ambiguous
    assert "resolve_entity" in render_evidence(build_evidence(box))  # nothing citable yet
    box.call("trace_upstream", {"column_id": "fct.total"})
    assert "resolve_entity" not in render_evidence(build_evidence(box))
    box.call("resolve_entity", {"text": "x_id"})  # three-way tie
    assert "(ambiguous)" in render_evidence(build_evidence(box))


def test_trim_drops_most_distant_first(box: Toolbox):
    box.call("trace_upstream", {"column_id": "fct_star.total"})
    items = build_evidence(box)
    far = max(items, key=lambda it: it.priority)
    kept, dropped = trim(items, lambda its: len(its) <= len(items) - 1)
    assert dropped == [far.id]
    assert min(it.priority for it in kept) == 1  # the edge next to the queried column survives
    kept, dropped = trim(items, lambda its: False)
    assert kept == [] and len(dropped) == 3


def test_error_line_does_not_repeat_suggestions(box: Toolbox):
    box.call("trace_upstream", {"column_id": "fct.totl"})
    line = tool_errors(box)[0]
    assert line.lower().count("did you mean") == 1
