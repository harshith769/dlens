"""B6 (dev-75, s12-design B6): a model named with ``_`` read as a space settles a tie, and a
yes/no question whose columns are linked by resolve_entity (not written as exact ids) gets an
``r_`` fact. loop.py only; the linker is untouched."""

from dlens.agent.loop import Agent, _named_candidate, _named_once
from dlens.agent.tools import Toolbox

from .conftest import call, done, draft

MODELS = ["stg_orders", "int_orders", "orders", "orders_daily"]


def test_spaced_model_name_picks_its_candidate() -> None:
    tie = ["stg_orders.x", "int_orders.x"]
    assert _named_candidate("where does x in stg orders come from?", tie, MODELS) == "stg_orders.x"
    assert _named_candidate("x in int orders", tie, MODELS) == "int_orders.x"
    assert _named_candidate("x in the orders", tie, MODELS) is None


def test_a_word_prefix_model_does_not_match() -> None:
    tie = ["orders.total", "orders_daily.total"]
    assert _named_candidate("total in orders daily", tie, MODELS) == "orders_daily.total"
    assert not _named_once("total in orders daily", ["orders.total", "x.total"], MODELS)


def test_underscores_still_match() -> None:
    tie = ["stg_orders.x", "int_orders.x"]
    assert _named_candidate("x in stg_orders", tie, MODELS) == "stg_orders.x"
    assert _named_candidate("stg_orders.x", tie, MODELS) == "stg_orders.x"


def _facts(box: Toolbox) -> list[dict]:
    return [r.llm_payload for r in box.log if r.tool == "reachability"]


def _ask(box: Toolbox, make_client, question: str, *queries: str) -> Agent:
    resolves = [call("resolve_entity", text=q) for q in queries]
    client, _ = make_client([*resolves, done(), draft("Yes.", reach_verdict="yes")] + [draft()] * 2)
    agent = Agent(client, box)
    agent.ask(question)
    return agent


def test_linked_columns_get_a_fact(box: Toolbox, make_client) -> None:
    _ask(box, make_client, "Does raw amt affect fct star total?", "raw amt", "fct star total")
    [fact] = _facts(box)
    assert fact["fact"].startswith("raw.amt reaches fct_star.total")


def test_depend_reverses_the_linked_order(box: Toolbox, make_client) -> None:
    _ask(box, make_client, "Does fct star total depend on raw amt?", "fct star total", "raw amt")
    [fact] = _facts(box)
    assert fact["fact"].startswith("raw.amt reaches fct_star.total")


def test_the_order_is_the_question_order_not_the_call_order(box: Toolbox, make_client) -> None:
    _ask(box, make_client, "Does raw amt affect fct star total?", "fct star total", "raw amt")
    [fact] = _facts(box)
    assert fact["fact"].startswith("raw.amt reaches fct_star.total")


def test_a_tie_the_question_settles_by_a_spaced_model_name(box: Toolbox, make_client) -> None:
    # "fct total" ties fct.total / fct_star.total; "fct" (written) names one of them
    _ask(box, make_client, "Does raw amt affect fct total?", "raw amt", "fct total")
    [fact] = _facts(box)
    assert fact["fact"].startswith("raw.amt reaches fct.total")


def test_one_unsettled_tie_gives_no_fact(box: Toolbox, make_client) -> None:
    _ask(box, make_client, "Does raw amt affect the total?", "raw amt", "total")
    assert _facts(box) == []


def test_three_linked_columns_give_no_fact(box: Toolbox, make_client) -> None:
    question = "Does raw amt affect stg amount and fct star total?"
    _ask(box, make_client, question, "raw amt", "stg amount", "fct star total")
    assert _facts(box) == []


def test_a_query_not_in_the_question_gives_no_fact(box: Toolbox, make_client) -> None:
    _ask(
        box, make_client, "Does the raw amount affect fct star total?", "raw amt", "fct star total"
    )
    assert _facts(box) == []


# -- B6 addition (owner, 21 Oct 2026): upstream of / downstream of / derived from ---------------


def _fact_for(box: Toolbox, make_client, question: str, *queries: str) -> str | None:
    _ask(box, make_client, question, *queries)
    facts = _facts(box)
    return facts[0]["fact"] if facts else None


def test_downstream_of_asks_the_second_named_reaches_the_first(box, make_client) -> None:
    fact = _fact_for(box, make_client, "Is fct_star.total downstream of raw.amt?")
    assert fact is not None and fact.startswith("raw.amt reaches fct_star.total")


def test_downstream_of_the_other_way(box, make_client) -> None:
    fact = _fact_for(box, make_client, "Is raw.amt downstream of fct_star.total?")
    assert fact is not None and fact.startswith("fct_star.total does NOT reach raw.amt")


def test_upstream_of_keeps_the_order(box, make_client) -> None:
    fact = _fact_for(box, make_client, "Is raw.amt upstream of fct_star.total?")
    assert fact is not None and fact.startswith("raw.amt reaches fct_star.total")
    box.reset()
    fact = _fact_for(box, make_client, "Is fct_star.total upstream of raw.amt?")
    assert fact is not None and fact.startswith("fct_star.total does NOT reach raw.amt")


def test_negated_wording_keeps_the_direction(box, make_client) -> None:
    fact = _fact_for(box, make_client, "Is fct_star.total not downstream of raw.amt?")
    assert fact is not None and fact.startswith("raw.amt reaches fct_star.total")


def test_derived_from_reverses(box, make_client) -> None:
    fact = _fact_for(box, make_client, "Is fct_star.total derived from raw.amt?")
    assert fact is not None and fact.startswith("raw.amt reaches fct_star.total")


def test_one_column_gets_no_fact(box, make_client) -> None:
    assert _fact_for(box, make_client, "What is downstream of raw.amt?") is None


def test_dev72_shape_exact_ids(box, make_client) -> None:
    question = "Is fct_star.total downstream of stg.amount in the lineage?"
    fact = _fact_for(box, make_client, question)
    assert fact is not None and fact.startswith("stg.amount reaches fct_star.total")


def test_dev75_shape_name_words(box, make_client) -> None:
    """Both columns written as words with a model named by spaced words ("fct star"), linked by
    resolve_entity, asked with "downstream of"."""
    question = "Is total in fct star downstream of amt in raw in the lineage?"
    fact = _fact_for(box, make_client, question, "total in fct star", "amt in raw")
    assert fact is not None and fact.startswith("raw.amt reaches fct_star.total")
