"""The regenerate budget (s12-design A6): a two-stage bound. The answer prompt is trimmed to
cap - REGENERATE_RESERVE (the larger of a JSON repair turn and a minimal regenerate turn); the
regenerate's failure list then fills the room actually left, and is skipped (salvage) when not even
the minimal list fits. No call is ever sent over the cap."""

from __future__ import annotations

from dlens.agent import loop, prompts
from dlens.agent.answer import DRAFT_SCHEMA
from dlens.agent.evidence import build_evidence, render_evidence
from dlens.agent.llm.tokens import estimate_tokens
from dlens.agent.llm.types import LLMResponse, Message
from dlens.agent.loop import (
    MAX_REGENERATE_FAILURES,
    REGEN_FACT_CHARS,
    REGEN_ITEM_CHARS,
    REGEN_MESSAGE_CHARS,
    REGENERATE_RESERVE,
    REPAIR_ERROR_CHARS,
    ask,
    fact_line,
    failure_line,
    list_tokens,
    more_line,
    regenerate_lines,
)

from .conftest import call, done, draft

Q = "where does fct_star.total come from?"
BAD_IDS = [f"e_0000{i:04x}" for i in range(12)]  # never emitted: each fails R2


def _user(text: str) -> int:
    return estimate_tokens([Message(role="user", content=text)])


def test_reserve_is_the_larger_of_the_repair_and_the_minimal_regenerate() -> None:
    repair = _user(prompts.ANSWER_REPAIR.format(error="y" * REPAIR_ERROR_CHARS))
    worst = failure_line(
        "answer_text", "R4.hallucinated", "x" * REGEN_ITEM_CHARS, "y" * REGEN_MESSAGE_CHARS
    )
    minimal = _user(
        prompts.REGENERATE.format(
            failures="\n".join(
                [fact_line("r_00000000", "z" * REGEN_FACT_CHARS), worst, more_line(999)]
            )
        )
    )
    assert REGENERATE_RESERVE == max(repair, minimal)
    assert MAX_REGENERATE_FAILURES == 9  # one line per rule R1-R9


def _failures(n: int) -> list[tuple[str, str, str, str]]:
    rules = ["R9", "R2", "R7", "R4.unsupported", "R1", "R3", "R8", "R5", "R6"]
    return [(f"claim {i}", rules[i % len(rules)], "x" * 200, "m" * 300) for i in range(n)]


def test_room_for_exactly_the_minimal_message() -> None:
    fact = fact_line("r_12345678", "a reaches b in 2 hops (graph check: through direct edges)")
    fs = _failures(30)
    first = failure_line(*sorted(fs, key=lambda f: loop.RULE_ORDER.index(f[1][:2]))[0])
    room = list_tokens([fact, first, more_line(29)])
    lines = regenerate_lines(fs, fact, room)
    assert lines == [fact, first, more_line(29)]
    assert regenerate_lines(fs, fact, room - 1) == [fact]  # no failure line: the caller skips


def test_ample_room_lists_up_to_the_cap_in_rule_order_with_clipped_parts() -> None:
    lines = regenerate_lines(_failures(30), None, 10_000)
    body, last = lines[:-1], lines[-1]
    assert len(body) == MAX_REGENERATE_FAILURES and last == "- +21 more failures"
    rules = [ln.split(": ", 1)[1].split(" ", 1)[0] for ln in body]
    assert [r[:2] for r in rules] == sorted(r[:2] for r in rules)  # R1 .. R9 order
    assert all(
        f" {'x' * REGEN_ITEM_CHARS}:" in ln and "x" * (REGEN_ITEM_CHARS + 1) not in ln
        for ln in body
    )
    assert all(len(ln.rsplit(": ", 1)[1]) == REGEN_MESSAGE_CHARS for ln in body)
    few = regenerate_lines(_failures(3), None, 10_000)
    assert len(few) == 3 and "more failures" not in few[-1]


def _cap_hook(box, holder, extra: int):
    """At the tool phase's end, set the cap to the full answer prompt + ``extra``."""

    def hook():
        items = build_evidence(box)
        user = prompts.answer_user(Q, render_evidence(items), [])
        full = estimate_tokens(
            [
                Message(role="system", content=prompts.ANSWER_SYSTEM),
                Message(role="user", content=user),
            ],
            None,
            DRAFT_SCHEMA,
        )
        holder["client"].max_input_tokens = full + extra
        return done()

    return hook


def _bad_draft():
    return draft("It comes from somewhere.", [(f"claim {i}", [i_]) for i, i_ in enumerate(BAD_IDS)])


def _llm_steps_fit(run) -> None:
    """No step and no run ended in InputTooLarge."""
    for s in run.record.steps:
        assert s.error is None or "InputTooLarge" not in s.error, s.error
    assert "InputTooLarge" not in (run.record.error or "")


def test_trimmed_evidence_and_a_forced_regenerate_fit(box, make_client) -> None:
    holder: dict = {}
    script = [
        call("trace_upstream", column_id="fct_star.total"),
        _cap_hook(box, holder, REGENERATE_RESERVE - 1),  # one token short: evidence is trimmed
        _bad_draft(),
        draft("It comes from somewhere."),
    ]
    client, prov = make_client(script)
    holder["client"] = client
    run = ask(Q, client, box)
    assert run.record.evidence["partial_evidence"]
    regen = [s for s in run.record.steps if s.phase == "regenerate"]
    assert len(regen) == 1 and regen[0].est_input_tokens <= client.max_input_tokens
    assert run.record.validation["regenerated"]
    _llm_steps_fit(run)
    sent = prov.requests[-1]["messages"][-1].content
    assert "more failures" in sent or sent.count("- claim") <= MAX_REGENERATE_FAILURES


def test_repair_and_regenerate_in_one_run_fit(box, make_client) -> None:
    holder: dict = {}
    script = [
        call("trace_upstream", column_id="fct_star.total"),
        _cap_hook(box, holder, REGENERATE_RESERVE - 1),
        LLMResponse(text="not json " * 80),
        _bad_draft(),
        draft("It comes from somewhere."),
    ]
    client, _ = make_client(script)
    holder["client"] = client
    run = ask(Q, client, box)
    phases = [s.phase for s in run.record.steps if s.is_llm_call]
    assert phases[-3:] == ["answer", "repair", "regenerate"]
    assert all(s.est_input_tokens <= client.max_input_tokens for s in run.record.steps)
    _llm_steps_fit(run)


def test_no_room_skips_the_regenerate_and_salvages(box, make_client, monkeypatch) -> None:
    monkeypatch.setattr(loop, "REGENERATE_RESERVE", 0)  # trim leaves no room for the turn
    holder: dict = {}
    script = [
        call("trace_upstream", column_id="fct_star.total"),
        _cap_hook(box, holder, 0),  # the answer prompt fills the cap exactly
        _bad_draft(),
    ]
    client, prov = make_client(script)
    holder["client"] = client
    run = ask(Q, client, box)
    assert [s.phase for s in run.record.steps if s.phase == "regenerate"] == []
    assert run.record.stop_reason.endswith("+regenerate_skipped_budget")
    v = run.record.validation
    assert v["regenerated"] is False and v["warning"] is True
    assert run.answer.validation_warning
    _llm_steps_fit(run)
    assert not prov.script  # nothing left unsent: no regenerate call was made
