"""scripts/paraphrase_questions.py: drift flags and picking, with a fake chat (no model)."""

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).parents[2]
sys.path.insert(0, str(ROOT / "scripts"))
import paraphrase_questions as pq  # noqa: E402

T_TRACE = "Where does fct_orders.item_count come from?"
T_LINEAGE = "Which columns are downstream of stg_order_items.quantity in the lineage?"
T_YESNO = "If raw_payments.created_at changes, does it affect fct_payment_events.event_at?"
T_MULTI = "Where does stg_product_costs.product_id come from, and who owns it?"


@pytest.mark.parametrize(
    ("template", "cand", "flag"),
    [
        (T_TRACE, "What is the source of the item count?", "id_dropped"),
        (T_TRACE, "What feeds fct_orders.item_count and fct_orders.order_id?", "id_added"),
        (T_TRACE, "What happens downstream if fct_orders.item_count changes?", "intent_changed"),
        (T_YESNO, "Explain why raw_payments.created_at affects fct_payment_events.event_at.",
         "intent_changed"),
        (T_LINEAGE, "What is affected when stg_order_items.quantity changes?", "lineage_dropped"),
        (T_LINEAGE, "Which downstream columns change if stg_order_items.quantity does?",
         "value_wording"),
        (T_MULTI, "Where does stg_product_costs.product_id come from?", "part_dropped"),
        (T_TRACE, "Here is the rewrite: where does fct_orders.item_count come from?", "format"),
        (T_TRACE, "fct_orders.item_count?", "length"),
        (T_TRACE, "Where does fct_orders.item_count come from", "unchanged"),
        (T_TRACE, "Hey, where does fct_orders.item_count come from?", "near_unchanged"),
    ],
)  # fmt: skip
def test_flags(template: str, cand: str, flag: str) -> None:
    assert flag in pq.check(template, cand)


@pytest.mark.parametrize(
    ("template", "cand"),
    [
        (T_TRACE, "What is the source of fct_orders.item_count?"),
        (T_LINEAGE, "In the lineage, what sits downstream of stg_order_items.quantity?"),
        (T_YESNO, "Would a change to raw_payments.created_at affect fct_payment_events.event_at?"),
        (T_MULTI, "What is the origin of stg_product_costs.product_id, and who is its owner?"),
    ],
)
def test_clean_paraphrases_pass(template: str, cand: str) -> None:
    assert pq.check(template, cand) == []


def test_entity_words_for_name_word_mentions() -> None:
    t = "Where does refund reason come from?"
    assert "entity_changed" in pq.check(
        t, "Where does the return cause come from?", "refund reason"
    )
    assert pq.check(t, "What is the source of the refund reasons?", "refund reason") == []


def test_paraphrase_sees_template_only_and_picks_first_clean() -> None:
    seen: list[str] = []
    replies = iter(["What is fct_orders.order_total?", "Source of fct_orders.item_count?",
                    "x"])  # fmt: skip

    def chat(hint: str, template: str) -> str:
        seen.append(template)
        return next(replies)

    q = {
        "id": "dev-99", "template_question": T_TRACE, "question": T_TRACE,
        "review_flags": ["paraphrase_pending"], "gold": {"secret": 1},
        "target": "fct_orders.item_count", "mention": "fct_orders.item_count",
    }  # fmt: skip
    other = {"id": "dev-98", "review_flags": [], "question": "unchanged"}
    rows = pq.paraphrase([q, other], chat)
    assert seen == [T_TRACE] * 3  # template text only, nothing else
    assert len(rows) == 1 and rows[0]["pick"] == "Source of fct_orders.item_count?"
    assert rows[0]["pick_style"] == "short"
    assert rows[0]["candidates"][0]["flags"]  # the first reply changed the column


def test_no_clean_candidate_gives_no_pick() -> None:
    q = {"id": "dev-97", "template_question": T_TRACE, "review_flags": ["paraphrase_pending"]}
    rows = pq.paraphrase([q], lambda hint, t: "Where does it come from?")
    assert rows[0]["pick"] is None
    assert "| dev-97 | template |" in pq.render_md(rows)


def test_refuses_a_cloud_provider(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DLENS_PROVIDER", "gemini")
    monkeypatch.setattr(sys, "argv", ["paraphrase_questions.py"])
    assert pq.main() == 2


def test_seeded_pick_is_deterministic_and_only_clean():
    cands = [{"style": s, "text": s, "flags": f} for s, f in
             [("plain", []), ("short", ["length"]), ("conversational", [])]]  # fmt: skip
    picks = {pq.seeded_pick(cands, f"t1-{i:03d}", "salt:")["style"] for i in range(40)}
    assert picks == {"plain", "conversational"}
    assert pq.seeded_pick(cands, "t1-001", "salt:") == pq.seeded_pick(cands, "t1-001", "salt:")
    assert pq.seeded_pick([{"style": "x", "text": "x", "flags": ["format"]}], "k", "s") is None


def test_paraphrase_uses_the_id_field_and_seeded_pick():
    q = {
        "draft_id": "t1-007",
        "template_question": T_TRACE,
        "review_flags": ["paraphrase_pending"],
        "mention": "fct_orders.item_count",
    }

    def chat(hint: str, template: str) -> str:
        return "Which columns feed fct_orders.item_count?"

    rows = pq.paraphrase([q], chat, id_field="draft_id", pick_salt="s:")
    assert rows[0]["id"] == "t1-007" and rows[0]["pick"] is not None
