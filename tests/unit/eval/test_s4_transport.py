"""S13b F5 end to end through the S4 runner: a Gemini transport error is retried once by the loop;
when the retry fails too, that question ends as one failed record (a refusal with the
ProviderError) and the runner goes on to the next question. Before F5 the httpx exception
escaped the runner (pilot-design §3.1, dev-38). No network: a fake google-genai client."""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace as NS
from typing import Any

import pytest

pytest.importorskip("google.genai")

import httpx  # noqa: E402
from google.genai import types as gt  # noqa: E402

from dlens.agent.llm.base import LLMClient  # noqa: E402
from dlens.agent.llm.cache import ResponseCache  # noqa: E402
from dlens.agent.llm.gemini import GeminiProvider  # noqa: E402
from dlens.agent.llm.quota import QuotaCounter  # noqa: E402
from dlens.agent.llm.ratelimit import RateLimiter  # noqa: E402
from dlens.agent.loop import Agent  # noqa: E402
from dlens.agent.tools import Toolbox  # noqa: E402
from dlens.graph import build_graph_from_artifacts  # noqa: E402
from systems import s4  # noqa: E402

ROOT = Path(__file__).resolve().parents[3]
SS_TARGET = ROOT / "tests" / "fixtures" / "artifacts" / "synthetic_shop"
SS_PROJECT = ROOT / "corpora" / "synthetic_shop"
QUESTIONS = [json.loads(x) for x in (ROOT / "eval/questions/dev.jsonl").read_text().splitlines()]
DRAFT = {
    "answer_text": "See the evidence.",
    "claims": [],
    "confidence": "low",
    "refused": False,
    "refusal_reason": None,
    "reach_verdict": None,
    "clarification_candidates": [],
}


class Models:
    """Fails the first ``drops`` calls with a dropped connection, then answers like a model
    that stops the tool phase at once and writes an empty draft."""

    def __init__(self, drops: int) -> None:
        self.drops, self.calls = drops, 0

    def generate_content(self, **kw: Any) -> Any:
        self.calls += 1
        if self.calls <= self.drops:
            raise httpx.RemoteProtocolError("Server disconnected without sending a response.")
        schema = kw["config"].response_json_schema
        text = json.dumps(DRAFT) if schema else "I have enough evidence."
        return NS(
            candidates=[NS(content=NS(parts=[gt.Part(text=text)]))],
            usage_metadata=NS(prompt_token_count=9, candidates_token_count=3),
        )


def agent(tmp: Path, models: Models) -> Agent:
    prov = GeminiProvider("gemini-3.5-flash-lite", client=NS(models=models))
    client = LLMClient(
        prov,
        ResponseCache(tmp / "cache.sqlite"),
        QuotaCounter(tmp / "quota.sqlite", {"gemini": None}),
        RateLimiter(None),
    )
    graph = build_graph_from_artifacts(SS_TARGET)[0]
    return Agent(client, Toolbox(graph, SS_PROJECT), project=s4.CORPUS)


def test_one_drop_is_retried_and_the_question_answers(tmp_path: Path) -> None:
    models = Models(drops=1)
    (rec,) = s4.run(agent(tmp_path, models), QUESTIONS[:1])
    first, retry = rec.steps[0], rec.steps[1]
    assert first.error == "gemini call failed: RemoteProtocolError" and retry.error is None
    assert rec.error is None and not rec.final_answer["refused"]


def test_two_drops_fail_one_record_and_the_runner_continues(tmp_path: Path) -> None:
    models = Models(drops=2)
    recs = s4.run(agent(tmp_path, models), QUESTIONS[:2])
    assert [r.question_id for r in recs] == [q["id"] for q in QUESTIONS[:2]]
    failed, nxt = recs
    errs = [s.error for s in failed.steps if s.is_llm_call]
    assert errs == ["gemini call failed: RemoteProtocolError"] * 2  # the call and its one retry
    assert failed.error == "ProviderError: gemini call failed: RemoteProtocolError"
    assert failed.final_answer["refused"]
    assert nxt.error is None and not nxt.final_answer["refused"]  # the run went on
