"""S4 runner (s12-design A4): a fake-client run writes records and a manifest that metrics scores
without a legacy manifest; question ids are checked against the exact-text join; cache fields;
the cloud gate. No network: scripted provider, no index (hybrid off)."""

from __future__ import annotations

import json
import re
from collections.abc import Sequence
from pathlib import Path
from typing import Any

import pytest

# The agent client runs on the agent extra (httpx: the OpenAI-compatible adapter), as test_s1.
pytest.importorskip("httpx")

import metrics as M  # noqa: E402
from dlens.agent import loop  # noqa: E402
from dlens.agent.llm.base import LLMClient, Provider  # noqa: E402
from dlens.agent.llm.cache import ResponseCache  # noqa: E402
from dlens.agent.llm.quota import QuotaCounter  # noqa: E402
from dlens.agent.llm.ratelimit import RateLimiter  # noqa: E402
from dlens.agent.llm.types import LLMResponse, Message, ToolSpec, Usage  # noqa: E402
from dlens.agent.loop import Agent  # noqa: E402
from dlens.agent.runlog import RunRecord  # noqa: E402
from dlens.agent.tools import Toolbox  # noqa: E402
from dlens.graph import build_graph_from_artifacts  # noqa: E402
from systems import s4  # noqa: E402
from systems.manifest import manifest_path  # noqa: E402

ROOT = Path(__file__).resolve().parents[3]
SS_TARGET = ROOT / "tests" / "fixtures" / "artifacts" / "synthetic_shop"
SS_PROJECT = ROOT / "corpora" / "synthetic_shop"
QUESTIONS = [json.loads(x) for x in (ROOT / "eval/questions/dev.jsonl").read_text().splitlines()]
HEX64 = re.compile(r"^[0-9a-f]{64}$")


class Scripted(Provider):
    """Stops the tool phase at once (code gathers evidence for dotted ids) and answers."""

    name, model = "fake", "fake-1"

    def __init__(self) -> None:
        self.calls = 0

    @property
    def params(self) -> dict[str, Any]:
        return {"temperature": 0}

    def send(
        self,
        messages: Sequence[Message],
        tools: Sequence[ToolSpec] | None,
        response_schema: dict[str, Any] | None = None,
    ) -> LLMResponse:
        self.calls += 1
        if response_schema is None:
            return LLMResponse(text="I have enough evidence.", usage=Usage(input_tokens=9))
        body = {
            "answer_text": "See the evidence.",
            "claims": [],
            "confidence": "low",
            "refused": False,
            "refusal_reason": None,
            "reach_verdict": None,
            "clarification_candidates": [],
        }
        return LLMResponse(text=json.dumps(body), usage=Usage(input_tokens=9))


@pytest.fixture(scope="module")
def graph() -> Any:
    return build_graph_from_artifacts(SS_TARGET)[0]


def agent(graph: Any, tmp: Path, prov: Provider | None = None) -> Agent:
    prov = prov or Scripted()
    client = LLMClient(
        prov,
        ResponseCache(tmp / "cache.sqlite"),
        QuotaCounter(tmp / "quota.sqlite", {prov.name: None}),
        RateLimiter(None),
    )
    return Agent(client, Toolbox(graph, SS_PROJECT), project=s4.CORPUS)


def test_fake_run_writes_records_and_a_manifest_metrics_scores(graph: Any, tmp_path: Path) -> None:
    qs = QUESTIONS[:4]
    a = agent(graph, tmp_path)
    records = s4.run(a, qs)
    path = tmp_path / "out" / "s4-fake-1-dev.jsonl"
    s4.write_records(records, path)
    man = s4.manifest(records, path, a, None, "hybrid off (no index)")
    mpath = s4.write_manifest(path, man)
    assert mpath == manifest_path(path)

    loaded = [json.loads(x) for x in path.read_text().splitlines()]
    assert [r["run_id"] for r in loaded] == [f"s4-{q['id']}" for q in qs]
    for rec, q in zip(loaded, qs, strict=True):
        assert RunRecord.model_validate(rec).model_dump(mode="json") == rec  # round trip
        assert rec["project"] == "corpora/synthetic_shop"  # relative (no local paths)
        assert rec["question_id"] == q["id"] and rec["question"] == q["question"]
        assert rec["cache"] == "miss" and rec["tokens"]["cached_calls"] == 0

    m = json.loads(mpath.read_text())
    assert m["system"] == "s4-fake-1" and m["view"] == "raw|validated|augmented"
    assert m["required"] == [q["id"] for q in qs] and m["record_count"] == 4
    assert m["hybrid"] is False and m["index_key"] is None
    assert set(m["prompt_sha256"]) == {
        "tool_system",
        "answer_system",
        "draft_schema",
        "answer_repair",
        "tool_repair",
        "regenerate",
        "directives",
        "tool_specs",
    }
    assert all(HEX64.match(v) for v in m["prompt_sha256"].values())
    assert HEX64.match(m["agent_code_sha256"])
    ts = m["tool_settings"]
    assert (ts["max_llm_calls"], ts["max_tool_phase_calls"], ts["max_result_tokens"]) == (
        8,
        5,
        1500,
    )
    assert ts["defaults"]["impact_downstream"]["include_indirect"] is True
    assert ts["regenerate_reserve"] == loop.REGENERATE_RESERVE > 0
    assert ts["max_regenerate_failures"] == 9
    assert ts["defaults"]["trace_upstream"]["include_indirect"] is False
    calls = sum(r["tokens"]["llm_calls"] for r in loaded)
    assert m["cache"] == {
        "dir": "outside the repo",  # tmp_path; a repo cache dir is written relative
        "hits": 0,
        "misses": calls,
        "records": {"hit": 0, "miss": 4, "partial": 0},
    }
    assert m["quota"]["provider"] == "fake" and m["quota"]["daily_budget"] is None  # S13
    assert m["quota"]["used_today"] == calls
    assert m["model_identity"]["provider"] == "fake"
    assert str(Path.home()) not in mpath.read_text() + path.read_text()

    # metrics scores it with this manifest (no --legacy-manifest), raw and validated
    for view in ("raw", "validated"):
        out = tmp_path / f"report-{view}"
        argv = ["--records", str(path), "--system", "s4-fake", "--view", view, "--out", str(out)]
        assert M.main(argv) == 0
        assert out.with_suffix(".json").is_file()


def test_rerun_is_served_from_the_cache(graph: Any, tmp_path: Path) -> None:
    prov = Scripted()
    a = agent(graph, tmp_path, prov)
    s4.run(a, QUESTIONS[:2])
    first = prov.calls
    again = s4.run(a, QUESTIONS[:2])
    assert prov.calls == first  # nothing new sent
    assert [r.cache for r in again] == ["hit", "hit"]


def test_question_id_must_match_the_text_join(graph: Any, tmp_path: Path) -> None:
    rec = agent(graph, tmp_path).ask(QUESTIONS[0]["question"], question_id=QUESTIONS[1]["id"])
    with pytest.raises(ValueError, match="question_id"):
        s4.check_ids([rec.record], QUESTIONS)
    s4.check_ids([], QUESTIONS)


def test_cache_field_is_none_without_an_llm_call(graph: Any, tmp_path: Path) -> None:
    # an unknown column in a known model is refused by code before any LLM call
    run = agent(graph, tmp_path).ask("Where does fct_orders.no_such_column come from?")
    assert run.record.llm_calls == 0 and run.record.cache is None


def test_main_refuses_a_cloud_provider_without_allow_cloud(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    for k, v in {
        "DLENS_PROVIDER": "openai",
        "DLENS_OPENAI_BASE_URL": "https://x.example/v1",
        "DLENS_OPENAI_MODEL": "m-1",
        "DLENS_OPENAI_KEY_ENV": "S4_TEST_KEY",
        "S4_TEST_KEY": "k",
        "DLENS_OPENAI_DAILY_BUDGET": "5",
        "DLENS_CACHE_DIR": str(tmp_path / "c"),
        "DLENS_STATE_DIR": str(tmp_path / "s"),
    }.items():
        monkeypatch.setenv(k, v)
    monkeypatch.setattr(s4, "open_graph", lambda *a, **k: pytest.fail("graph opened before gate"))
    assert s4.main(["--out", str(tmp_path / "out"), "--limit", "1"]) == 2
    assert "--allow-cloud" in capsys.readouterr().err
    assert not (tmp_path / "out").exists()


# The S12b run reused by the qwen pilot row (pilot-design §1): a frozen record, never changes.
PILOT_AGENT_SHA = "a6fb5b2e49fe9a104c3828c402d186196601c50c4ea25dadef0dbc982952b424"
# The live agent code (S13b A2): updated in the same commit as every change under src/dlens/agent.
CURRENT_AGENT_SHA = "2a2d9b1e91e4c697488e8981c709ae932f1efd0cde8fdd88b7c912bae30dcd88"


def test_pilot_reuse_holds_agent_code_unchanged_since_s12b() -> None:
    """pilot-design §1: the qwen S4 pilot row reuses the S12b run; its manifest keeps that run's
    agent sha. Since S13b (post-pilot fixes) the live code differs, and its sha is pinned
    separately, so every agent-code change is a visible edit here (owner amendment A2)."""
    man = json.loads(
        (ROOT / "eval/runs/s4/s4-qwen3-4b-instruct-2507-q4-k-m-dev.manifest.json").read_text()
    )
    assert man["agent_code_sha256"] == PILOT_AGENT_SHA  # (i) the frozen pilot record
    assert s4.agent_code_sha256() == CURRENT_AGENT_SHA  # (ii) the live agent code
    now = s4.prompt_hashes()  # no index: the tool prompt and specs differ, the rest must not
    for key in ("answer_system", "draft_schema", "answer_repair", "tool_repair", "regenerate"):
        assert now[key] == man["prompt_sha256"][key], key
    assert now["directives"] == man["prompt_sha256"]["directives"]
