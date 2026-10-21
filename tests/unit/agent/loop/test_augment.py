"""G1 coverage completion (s12-design B1): code appends the direct inputs a trace returned and
the impact columns the answer left out, as ``origin: augmented`` claims, from tool results
already in the log (no new traversal), never on a refusal or a clarification, and counted only
in the S4-augmented view."""

import sys
from pathlib import Path

from dlens.agent.answer import Answer, Claim, Clarification
from dlens.agent.augment import augment
from dlens.agent.loop import Agent
from dlens.agent.tools import Toolbox
from dlens.lineage import Edge, EdgeKind

from ..tools.conftest import GROUP_BY_X_ID, make_shop
from ..validator.conftest import eid
from .conftest import P, _extend, call, done, draft

sys.path.insert(0, str(Path(__file__).resolve().parents[4] / "eval"))
import metrics  # noqa: E402

TWO_INPUTS = Edge(
    from_column=f"{P}.stg.x_id",
    to_column=f"{P}.fct.total",
    kind=EdgeKind.TRANSFORMATION,
    expression="sum(amount) + x_id",
    file="models/fct.sql",
    lines=(3, 3),
)


def _two_input_box(shop_root: Path) -> Toolbox:
    return Toolbox(_extend(make_shop(), {}, {}, [TWO_INPUTS]), shop_root)


def test_trace_adds_each_missing_direct_input_citing_its_edge(shop_root: Path) -> None:
    box = _two_input_box(shop_root)
    box.call("trace_upstream", {"column_id": "fct.total"})
    a_in, b_in = eid(box, "stg.amount", "fct.total"), eid(box, "stg.x_id", "fct.total")
    answer = Answer(
        answer_text="fct.total aggregates stg.amount.",
        claims=[Claim(text="fct.total aggregates stg.amount", edge_ids=[a_in])],
    )
    n_log = len(box.log)
    out = augment(answer, box, "trace_upstream")
    assert len(box.log) == n_log  # no new traversal
    [added] = [c for c in out.claims if c.origin == "augmented"]
    assert added.text == "stg.x_id is a direct input of fct.total." and added.edge_ids == [b_in]
    assert b_in in box.emitted_ids and b_in in out.citations
    assert out.answer_text == answer.answer_text and out.claims[0] == answer.claims[0]


def test_trace_with_every_input_named_adds_nothing(shop_root: Path) -> None:
    box = _two_input_box(shop_root)
    box.call("trace_upstream", {"column_id": "fct.total"})
    a_in = eid(box, "stg.amount", "fct.total")
    text = "fct.total is computed from stg.amount and stg.x_id"
    answer = Answer(answer_text=text, claims=[Claim(text=text, edge_ids=[a_in])])
    assert augment(answer, box, "trace_upstream") == answer


def test_trace_skips_indirect_and_deeper_edges(shop_root: Path) -> None:
    box = Toolbox(make_shop([GROUP_BY_X_ID]), shop_root)
    box.call("trace_upstream", {"column_id": "fct_star.total", "include_indirect": True})
    out = augment(Answer(answer_text="It comes from raw.amt."), box, "trace_upstream")
    assert [c.text for c in out.claims] == ["fct.total is a direct input of fct_star.total."]


def test_impact_adds_one_claim_per_group_from_the_full_side_set(box: Toolbox) -> None:
    r = box.call("impact_downstream", {"column_id": "raw.amt"})
    full = r.side_records["full"]["columns"]
    out = augment(Answer(answer_text="It affects stg.amount."), box, "impact_downstream")
    added = [c for c in out.claims if c.origin == "augmented"]
    named = {n for n in full if n != "stg.amount"}
    assert added and all(c.text.startswith("Also affected at depth ") for c in added)
    assert {n for c in added for n in named if n in c.text} == named
    vias = {full[n]["via"] for n in named}
    assert {i for c in added for i in c.edge_ids} == vias and vias <= set(out.citations)


def test_nothing_on_refusal_clarification_or_no_intent(box: Toolbox) -> None:
    box.call("trace_upstream", {"column_id": "fct.total"})
    refused = Answer.refusal("no")
    clar = Answer(answer_text="?", clarification=Clarification(question="?", candidates=["a"]))
    plain = Answer(answer_text="x")
    assert augment(refused, box, "trace_upstream") is refused
    assert augment(clar, box, "trace_upstream") is clar
    assert augment(plain, box, None) is plain


def test_views_raw_and_validated_exclude_augmented(box: Toolbox, make_client) -> None:
    client, _ = make_client(
        [
            call("trace_upstream", column_id="fct_star.total"),
            done(),
            lambda: draft(
                "fct_star.total comes from fct.total.",
                [
                    (
                        "fct_star.total comes from fct.total",
                        [eid(box, "fct.total", "fct_star.total")],
                    )
                ],
            ),
        ]
    )
    run = Agent(client, box).ask("Where does fct_star.total come from?")
    final = run.record.final_answer or {}
    origins = [c["origin"] for c in final["claims"]]
    assert "augmented" not in origins  # the only direct input is already named
    box2 = box
    client, _ = make_client(
        [
            call("trace_upstream", column_id="fct.total"),
            done(),
            draft("It is an aggregation in the fct model."),  # no claims: passes, names no input
        ]
    )
    run = Agent(client, box2).ask("Where does fct.total come from?")
    record = run.record.model_dump(mode="json")
    rec_claims = record["final_answer"]["claims"]
    assert any(c["origin"] == "augmented" for c in rec_claims)
    views = {v: metrics.from_record(record, v).claims for v in ("raw", "validated", "augmented")}
    assert all(c["origin"] != "augmented" for v in ("raw", "validated") for c in views[v])
    assert any(c["origin"] == "augmented" for c in views["augmented"])
