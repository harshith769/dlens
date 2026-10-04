"""Fixtures for the agent loop: the tiny hand-built shop graph (plus variants for the ambiguity
policy) and a scripted fake provider that records every request."""

from __future__ import annotations

import json
from collections.abc import Sequence
from datetime import datetime
from pathlib import Path
from typing import Any

import pytest

from dlens.agent.llm.base import LLMClient, Provider
from dlens.agent.llm.cache import ResponseCache
from dlens.agent.llm.quota import PACIFIC, QuotaCounter
from dlens.agent.llm.ratelimit import RateLimiter
from dlens.agent.llm.types import LLMResponse, Message, ToolCall, ToolSpec, Usage
from dlens.agent.runlog import RunLogger
from dlens.agent.tools import Toolbox
from dlens.graph import LineageGraph
from dlens.lineage import Edge, EdgeKind

from ..tools.conftest import FCT, RAW, STAR, STG, make_shop

P = "model.p"

# A 4-layer chain whose column names all tie for "refund amt" (like synthetic_shop's refunds).
CHAIN_SQL = {
    "models/r_stg.sql": "select\n    refund_amt\nfrom {{ ref('r_raw') }}\n",
    "models/r_int.sql": "select\n    sum(refund_amt) as refund_amount\nfrom {{ ref('r_stg') }}\n",
    "models/r_hist.sql": "select\n    refund_amount\nfrom {{ ref('r_int') }}\n",
}
# Unrelated models that each have a `total` column (ties with fct.total / fct_star.total).
OTHER_SQL = {
    "models/other.sql": "select\n    1 as total\n",
    "models/misc.sql": "select\n    2 as total\n",
}


def write_shop(root: Path) -> Path:
    (root / "models").mkdir(parents=True, exist_ok=True)
    (root / "seeds").mkdir(exist_ok=True)
    files = {
        "models/stg.sql": STG,
        "models/fct.sql": FCT,
        "models/star.sql": STAR,
        "seeds/raw.csv": RAW,
        "seeds/r_raw.csv": "refund_amt\n1\n",
        **CHAIN_SQL,
        **OTHER_SQL,
    }
    for rel, text in files.items():
        (root / rel).write_text(text)
    return root


def _extend(
    base: LineageGraph,
    cols: dict[str, tuple[str, str]],
    models: dict[str, dict[str, str]],
    edges: list[Edge],
) -> LineageGraph:
    g = base
    return LineageGraph(
        columns={
            **{c: dict(g.nx_graph.nodes[c]) for c in g.columns()},
            **{c: {"model": m, "name": n, "type": "int"} for c, (m, n) in cols.items()},
        },
        edges=[*g.edges(), *edges],
        depends_on=[],
        consumes=[("exposure.p.dash", f"{P}.fct_star")],
        models={**{m: g.model_info(m) or {} for m in g.model_ids()}, **models},
        exposures={"exposure.p.dash": {"name": "dash", "type": "dashboard"}},
        parse={},
    )


def make_chain_shop() -> LineageGraph:
    k = EdgeKind
    cols = {
        "seed.p.r_raw.refund_amt": ("seed.p.r_raw", "refund_amt"),
        f"{P}.r_stg.refund_amt": (f"{P}.r_stg", "refund_amt"),
        f"{P}.r_int.refund_amount": (f"{P}.r_int", "refund_amount"),
        f"{P}.r_hist.refund_amount": (f"{P}.r_hist", "refund_amount"),
    }
    models = {
        "seed.p.r_raw": {"resource_type": "seed", "name": "r_raw", "file": "seeds/r_raw.csv"},
        f"{P}.r_stg": {"resource_type": "model", "name": "r_stg", "file": "models/r_stg.sql"},
        f"{P}.r_int": {"resource_type": "model", "name": "r_int", "file": "models/r_int.sql"},
        f"{P}.r_hist": {"resource_type": "model", "name": "r_hist", "file": "models/r_hist.sql"},
    }

    def e(src: str, dst: str, kind: EdgeKind, file: str, expr: str) -> Edge:
        return Edge(
            from_column=src, to_column=dst, kind=kind, expression=expr, file=file, lines=(2, 2)
        )

    edges = [
        e(
            "seed.p.r_raw.refund_amt",
            f"{P}.r_stg.refund_amt",
            k.IDENTITY,
            "models/r_stg.sql",
            "refund_amt",
        ),
        e(
            f"{P}.r_stg.refund_amt",
            f"{P}.r_int.refund_amount",
            k.AGGREGATION,
            "models/r_int.sql",
            "sum(refund_amt)",
        ),
        e(
            f"{P}.r_int.refund_amount",
            f"{P}.r_hist.refund_amount",
            k.IDENTITY,
            "models/r_hist.sql",
            "refund_amount",
        ),
    ]
    return _extend(make_shop(), cols, models, edges)


def make_totals_shop(n_other: int) -> LineageGraph:
    """fct.total -> fct_star.total (one chain) plus ``n_other`` unrelated ``total`` columns."""
    names = ["other", "misc"][:n_other]
    cols = {f"{P}.{m}.total": (f"{P}.{m}", "total") for m in names}
    models = {
        f"{P}.{m}": {"resource_type": "model", "name": m, "file": f"models/{m}.sql"} for m in names
    }
    return _extend(make_shop(), cols, models, [])


class ScriptedProvider(Provider):
    """Returns queued responses (or raises queued exceptions) and records every request."""

    name = "ollama"
    model = "scripted-1"

    def __init__(self, script: Sequence[Any]) -> None:
        self.script = list(script)
        self.requests: list[dict[str, Any]] = []

    @property
    def params(self) -> dict[str, Any]:
        return {"temperature": 0}

    def send(
        self,
        messages: Sequence[Message],
        tools: Sequence[ToolSpec] | None,
        response_schema: dict[str, Any] | None = None,
    ) -> LLMResponse:
        self.requests.append(
            {"messages": list(messages), "tools": tools, "schema": response_schema}
        )
        if not self.script:
            raise AssertionError("scripted provider ran out of responses")
        item = self.script.pop(0)
        if callable(item):  # a hook run at send time (e.g. to change the client between phases)
            item = item()
        if isinstance(item, Exception):
            raise item
        return item


def call(name: str, **args: Any) -> LLMResponse:
    return LLMResponse(
        tool_calls=[ToolCall(id="call_0", name=name, arguments=args)],
        usage=Usage(input_tokens=100, output_tokens=10),
    )


def calls(*pairs: tuple[str, dict[str, Any]]) -> LLMResponse:
    return LLMResponse(
        tool_calls=[ToolCall(id=f"call_{i}", name=n, arguments=a) for i, (n, a) in enumerate(pairs)]
    )


def done(text: str = "I have enough evidence.") -> LLMResponse:
    return LLMResponse(text=text)


def draft(answer_text: str = "ok", claims: list[tuple[str, list[str]]] | None = None, **kw: Any):
    body = {
        "answer_text": answer_text,
        "claims": [{"text": t, "ids": ids} for t, ids in claims or []],
        "confidence": "high",
        "refused": False,
        **kw,
    }
    return LLMResponse(text=json.dumps(body))


@pytest.fixture
def shop_root(tmp_path: Path) -> Path:
    return write_shop(tmp_path / "proj")


@pytest.fixture
def box(shop_root: Path) -> Toolbox:
    return Toolbox(make_shop(), shop_root)


@pytest.fixture
def make_client(tmp_path: Path):
    def _make(script: Sequence[Any], cap: int = 3000):
        prov = ScriptedProvider(script)
        client = LLMClient(
            prov,
            ResponseCache(tmp_path / f"cache-{id(prov)}" / "llm.sqlite"),
            QuotaCounter(
                tmp_path / "state" / "quota.sqlite",
                {"ollama": None},
                lambda: datetime(2026, 10, 5, 12, tzinfo=PACIFIC),
            ),
            RateLimiter(None),
            max_input_tokens=cap,
        )
        return client, prov

    return _make


@pytest.fixture
def logger(tmp_path: Path) -> RunLogger:
    return RunLogger(tmp_path / "runs")
