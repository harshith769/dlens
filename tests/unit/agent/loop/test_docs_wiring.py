"""search_docs without an index (the demo install, s12-design B4): not advertised, not callable,
and the tool prompt is TOOL_SYSTEM unchanged; the loop picks the prompt from the toolbox."""

from dlens.agent import prompts
from dlens.agent.loop import Agent
from dlens.agent.tools import TOOL_SPECS, Toolbox

from .conftest import done


def test_without_an_index_nothing_changes(box: Toolbox) -> None:
    assert not box.has_docs and box.specs() == list(TOOL_SPECS)
    assert prompts.tool_system(False) == prompts.TOOL_SYSTEM
    r = box.call("search_docs", {"query": "x"})
    assert r.llm_payload["error"]["code"] == "unknown_tool"
    assert "search_docs" not in r.llm_payload["error"]["suggestions"]


def test_the_loop_sends_the_toolbox_prompt(box: Toolbox, make_client) -> None:
    client, prov = make_client([done()])
    Agent(client, box).ask("What does it mean?")  # no evidence: refused before an answer call
    first = prov.requests[0]
    assert first["messages"][0].content == prompts.TOOL_SYSTEM
    assert [s.name for s in first["tools"]] == [s.name for s in TOOL_SPECS]


def test_with_docs_the_step_sentence_is_appended_once() -> None:
    text = prompts.tool_system(True)
    assert text.count(prompts.SEARCH_DOCS_STEP) == 1
    assert text.replace(prompts.SEARCH_DOCS_STEP, "") == prompts.TOOL_SYSTEM
