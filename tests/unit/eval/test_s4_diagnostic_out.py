"""S13b step 9: the runner can write a labelled diagnostic run (`--prefix`, `--purpose`) without
touching the default file names. No network: a scripted provider and the fixture graph."""

from __future__ import annotations

import json
from collections.abc import Sequence
from pathlib import Path
from typing import Any

import pytest

pytest.importorskip("httpx")

import dlens.agent.llm as llm  # noqa: E402
from dlens.agent.llm.base import LLMClient, Provider  # noqa: E402
from dlens.agent.llm.cache import ResponseCache  # noqa: E402
from dlens.agent.llm.quota import QuotaCounter  # noqa: E402
from dlens.agent.llm.ratelimit import RateLimiter  # noqa: E402
from dlens.agent.llm.types import LLMResponse, Message, ToolSpec, Usage  # noqa: E402
from dlens.graph import build_graph_from_artifacts  # noqa: E402
from systems import s4  # noqa: E402

ROOT = Path(__file__).resolve().parents[3]
SS_TARGET = ROOT / "tests" / "fixtures" / "artifacts" / "synthetic_shop"


class Quiet(Provider):
    name, model = "fake", "fake-1"
    local = True  # not a cloud provider (the --allow-cloud gate)

    @property
    def params(self) -> dict[str, Any]:
        return {"temperature": 0}

    def send(
        self,
        messages: Sequence[Message],
        tools: Sequence[ToolSpec] | None,
        response_schema: dict[str, Any] | None = None,
    ) -> LLMResponse:
        body = {"answer_text": "x", "claims": [], "confidence": "low", "refused": False}
        text = json.dumps(body) if response_schema else "done"
        return LLMResponse(text=text, usage=Usage(input_tokens=9))


@pytest.fixture
def patched(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Path:
    prov = Quiet()
    client = LLMClient(
        prov,
        ResponseCache(tmp_path / "c.sqlite"),
        QuotaCounter(tmp_path / "q.sqlite", {prov.name: None}),
        RateLimiter(None),
    )
    monkeypatch.setattr(llm, "make_client", lambda: client)
    graph = build_graph_from_artifacts(SS_TARGET)[0]
    monkeypatch.setattr(s4, "open_graph", lambda *_a, **_k: (graph, None, "hybrid off (test)"))
    return tmp_path / "out"


def test_prefix_and_purpose_label_a_diagnostic_run(patched: Path) -> None:
    purpose = "diagnostic, post-fix dev; not a result; does not replace the pilot table"
    argv = ["--out", str(patched), "--limit", "1", "--prefix", "s13b", "--purpose", purpose]
    assert s4.main(argv) == 0
    assert sorted(p.name for p in patched.iterdir()) == [
        "s13b-fake-1-dev.jsonl",
        "s13b-fake-1-dev.manifest.json",
    ]
    man = json.loads((patched / "s13b-fake-1-dev.manifest.json").read_text())
    assert man["purpose"] == purpose and man["records_file"] == "s13b-fake-1-dev.jsonl"


def test_defaults_are_unchanged(patched: Path) -> None:
    assert s4.main(["--out", str(patched), "--limit", "1"]) == 0
    man = json.loads((patched / "s4-fake-1-dev.manifest.json").read_text())
    assert "purpose" not in man
