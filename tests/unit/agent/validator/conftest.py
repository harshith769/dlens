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


def answer(text: str, *claims: tuple[str, list[str]], verdict: str | None = None) -> Answer:
    """An answer; ``verdict`` sets the structured ``reach_verdict`` (source ``llm``), which R9
    holds to the r_ fact (s12-design A2)."""
    out = []
    for t, ids in claims:
        edges = [i for i in ids if i.startswith("e_")]
        out.append(Claim(text=t, edge_ids=edges, chunk_ids=[i for i in ids if i not in edges]))
    return Answer(
        answer_text=text,
        claims=out,
        confidence="high",
        reach_verdict=verdict,  # type: ignore[arg-type]
        reach_verdict_source="llm" if verdict else None,
    )


@pytest.fixture
def traced(request: pytest.FixtureRequest) -> Toolbox:
    """fct_star.total and fct_star.x_id traced, and fct's SQL around total fetched."""
    tb: Toolbox = request.getfixturevalue("box")
    tb.call("trace_upstream", {"column_id": "fct_star.total"})
    tb.call("trace_upstream", {"column_id": "fct_star.x_id"})
    tb.call("get_model_sql", {"model_id": "fct", "around_column": "total"})
    return tb


# -- B3 label-only check (s12-design B3, ADR 0025) ----------------------------------------------
# Every validate() / salvage() call made by this directory's deterministic tests is digested with
# the S12b labels stripped (claim ``origin`` and the new Answer fields) and compared with the
# snapshot recorded on the pre-B3 code. So B3's labels may change no rule outcome: failures,
# repairs, completions, dropped claims, counts, the cleaned answer and salvage's answer.
# Re-record (only with an owner-approved validator change): DLENS_WRITE_VALIDATOR_SNAPSHOT=1.

import hashlib  # noqa: E402
import json  # noqa: E402
import os  # noqa: E402
from collections.abc import Callable, Iterator  # noqa: E402
from pathlib import Path  # noqa: E402
from typing import Any  # noqa: E402

from dlens.agent import loop as _loop  # noqa: E402
from dlens.agent import validator as _validator  # noqa: E402

SNAPSHOT = Path(__file__).parents[3] / "fixtures" / "validator" / "outcomes_pre_b3.json"
LABEL_KEYS = ("origin", "premise_corrected", "uncovered_parts", "interpretation",
              "interpretation_source")  # fmt: skip
UNRECORDED = ("test_property.py",)  # hypothesis draws differ run to run
_recorded: dict[str, list[str]] = {}


def _strip(x: Any) -> Any:
    if isinstance(x, dict):
        return {k: _strip(v) for k, v in x.items() if k not in LABEL_KEYS}
    if isinstance(x, list):
        return [_strip(v) for v in x]
    return x


def outcome_digest(obj: Any) -> str:
    dumped = obj.model_dump(mode="json") if obj is not None else None
    return hashlib.sha256(json.dumps(_strip(dumped), sort_keys=True).encode()).hexdigest()[:16]


@pytest.fixture(autouse=True)
def _record_outcomes(
    request: pytest.FixtureRequest, monkeypatch: pytest.MonkeyPatch
) -> Iterator[None]:
    node = request.node.nodeid.split("/validator/", 1)[-1]
    if node.startswith(UNRECORDED):
        yield
        return
    seen: list[str] = []

    def wrap(fn: Callable[..., Any]) -> Callable[..., Any]:
        def inner(*args: Any, **kwargs: Any) -> Any:
            out = fn(*args, **kwargs)
            seen.append(f"{fn.__name__}:{outcome_digest(out)}")
            return out

        return inner

    for name in ("validate", "salvage"):
        real = getattr(_validator, name)
        for mod in (_validator, _loop, request.module):
            if getattr(mod, name, None) is real:
                monkeypatch.setattr(mod, name, wrap(real))
    yield
    if os.environ.get("DLENS_WRITE_VALIDATOR_SNAPSHOT"):
        _recorded[node] = seen
        data = json.loads(SNAPSHOT.read_text()) if SNAPSHOT.is_file() else {}
        SNAPSHOT.parent.mkdir(parents=True, exist_ok=True)
        SNAPSHOT.write_text(json.dumps({**data, **_recorded}, indent=1, sort_keys=True) + "\n")
        return
    want = json.loads(SNAPSHOT.read_text()).get(node)
    if want is not None:  # tests written after B3 are not in the pre-B3 snapshot
        assert seen == want, f"{node}: validator outcome changed with labels stripped"
