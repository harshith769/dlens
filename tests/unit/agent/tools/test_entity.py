from dlens.agent.tools import Toolbox
from dlens.agent.tools.entity import tokens


def ids(box: Toolbox, text: str, k: int = 5) -> list[str]:
    r = box.call("resolve_entity", {"text": text, "k": k})
    assert not r.is_error
    return [c["id"] for c in r.llm_payload["candidates"]]


def test_tokens_normalise_case_separators_plurals_and_abbreviations() -> None:
    assert tokens("OrderDate") == ["order", "date"]
    assert tokens("order_dates") == ["order", "date"]
    assert tokens("Amt") == ["amount"]
    assert tokens("qty_per_order") == ["quantity", "per", "order"]
    assert tokens("status") == tokens("STATUS")  # crude plural stripping is applied to both sides


def test_exact_ids_win(toolbox: Toolbox) -> None:
    assert ids(toolbox, "fct.total")[0] == "fct.total"
    assert ids(toolbox, "FCT.TOTAL")[0] == "fct.total"
    assert ids(toolbox, "model.p.fct.total")[0] == "fct.total"
    r = toolbox.call("resolve_entity", {"text": "fct.total"})
    assert r.llm_payload["candidates"][0]["score"] == 1.0


def test_abbreviation_and_literal_tiers_stay_apart(toolbox: Toolbox) -> None:
    r = toolbox.call("resolve_entity", {"text": "amt"})
    top = r.llm_payload["candidates"][0]
    assert (top["id"], top["match"]) == ("raw.amt", "exact")  # literal beats normalised
    assert "stg.amount" in ids(toolbox, "amt")  # but the abbreviation still finds it
    assert ids(toolbox, "stg.amt")[0] == "stg.amount"


def test_models_are_candidates(toolbox: Toolbox) -> None:
    r = toolbox.call("resolve_entity", {"text": "fct_star"})
    top = r.llm_payload["candidates"][0]
    assert top["kind"] == "model" and top["id"] == "fct_star" and top["score"] == 1.0


def test_no_match_and_bad_args(toolbox: Toolbox) -> None:
    r = toolbox.call("resolve_entity", {"text": "zzzzqqqq"})
    assert r.llm_payload["candidates"] == [] and "notes" in r.llm_payload
    assert (
        toolbox.call("resolve_entity", {"text": "  "}).llm_payload["error"]["code"]
        == "invalid_argument"
    )
    assert toolbox.call("resolve_entity", {"text": "x", "k": 0}).is_error
    assert (
        len(toolbox.call("resolve_entity", {"text": "x_id", "k": 2}).llm_payload["candidates"]) <= 2
    )


def test_ambiguity_flag(toolbox: Toolbox) -> None:
    assert toolbox.call("resolve_entity", {"text": "x_id"}).llm_payload["ambiguous"] is True
    assert toolbox.call("resolve_entity", {"text": "fct.total"}).llm_payload["ambiguous"] is False


def test_resolve_does_not_emit_edge_ids(toolbox: Toolbox) -> None:
    toolbox.call("resolve_entity", {"text": "amt"})
    assert toolbox.emitted_ids == frozenset()
