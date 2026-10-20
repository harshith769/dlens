"""Impact payload shape B on every dev impact target (s12-design A5.2, owner decision 20 Oct 2026):
each payload lists every column of its uncapped result, or is flagged ``truncated`` with visible
"+K more" lines and the full set in ``side_records``; the tool-phase digest keeps every shown id
at both levels. Offline: the committed synthetic_shop fixture graph, no LLM."""

import json
import re
from pathlib import Path

import pytest

from dlens.agent.context import digest
from dlens.agent.tools import Toolbox
from dlens.agent.tools.budget import MAX_RESULT_TOKENS, payload_tokens
from dlens.graph import build_graph_from_artifacts

ROOT = Path(__file__).resolve().parents[4]
SS_TARGET = ROOT / "tests" / "fixtures" / "artifacts" / "synthetic_shop"
SS_PROJECT = ROOT / "corpora" / "synthetic_shop"
ID = re.compile(r"\be_[0-9a-f]{8}\b")
QUESTIONS = [json.loads(x) for x in (ROOT / "eval/questions/dev.jsonl").read_text().splitlines()]
TARGETS = sorted(
    {q["target"] for q in QUESTIONS if q["type"] == "impact" and q["subtype"] == "downstream"}
)
# the widest synthetic_shop column (175 columns direct + indirect; in no dev question)
WIDE = "stg_products.product_id"


@pytest.fixture(scope="module")
def box() -> Toolbox:
    return Toolbox(build_graph_from_artifacts(SS_TARGET)[0], SS_PROJECT)


@pytest.mark.parametrize("target", [*TARGETS, WIDE])
def test_payload_lists_every_column_or_flags_the_cut(box: Toolbox, target: str) -> None:
    g = box.graph
    try:
        col = g.resolve(target)
    except Exception:
        pytest.skip(f"{target} is not a single graph column")
    box.reset()
    r = box.call("impact_downstream", {"column_id": target})
    p, side = r.llm_payload, r.side_records
    uncapped = {g.display_name(c) for c in g.downstream(col, include_indirect=True).via}
    shown = [it.rsplit(" ", 1)[0] for v in p["columns_by_depth"].values() for it in v]
    assert len(shown) == len(set(shown))  # each column once
    assert set(side["full"]["columns"]) == uncapped  # the full set, always
    assert payload_tokens(p) <= MAX_RESULT_TOKENS
    if p["truncated"]:
        assert p["more"] and p["dropped"]["columns"] == len(uncapped) - len(shown)
        assert sum(int(m.split()[0][1:]) for m in p["more"]) == p["dropped"]["columns"]
    else:
        assert set(shown) == uncapped and "more" not in p
    # digest keeps every shown id at both levels
    ids = set(ID.findall(json.dumps(p)))
    for level in (1, 2):
        assert ids <= set(ID.findall(json.dumps(digest(r, level))))


def test_every_dev_impact_target_fits_uncut(box: Toolbox) -> None:
    """Measured, not assumed: no dev impact payload is cut under shape B."""
    cut = []
    for t in TARGETS:
        box.reset()
        r = box.call("impact_downstream", {"column_id": t})
        if not r.is_error and r.llm_payload["truncated"]:
            cut.append(t)
    assert cut == []
