"""S1 vector-RAG baseline (S11, docs/plans/s1-design.md): a fake-client run, the skip-and-pack
budget, ledger citations, the no-graph-facts rule, prompt parity with S4, the freeze, records,
manifest and the cloud gate. No network: fake embedder, scripted provider."""

from __future__ import annotations

import json
import re
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import Any

import pytest

# S1 runs on the agent extra (httpx: the OpenAI-compatible adapter); the core-install CI step has
# no extras, so this module skips there.
pytest.importorskip("httpx")

import metrics as M  # noqa: E402
from dlens.agent import prompts  # noqa: E402
from dlens.agent.answer import DRAFT_SCHEMA, Answer  # noqa: E402
from dlens.agent.llm.base import LLMClient, Provider  # noqa: E402
from dlens.agent.llm.cache import ResponseCache  # noqa: E402
from dlens.agent.llm.openai_compat import OpenAICompatProvider  # noqa: E402
from dlens.agent.llm.quota import QuotaCounter  # noqa: E402
from dlens.agent.llm.ratelimit import RateLimiter  # noqa: E402
from dlens.agent.llm.types import LLMResponse, Message, ProviderError, ToolSpec, Usage  # noqa: E402
from dlens.agent.runlog import RunRecord  # noqa: E402
from dlens.graph import LineageGraph, build_graph_from_artifacts  # noqa: E402
from dlens.retrieval.dense import FakeEmbedder  # noqa: E402
from dlens.retrieval.index import SearchIndex  # noqa: E402
from systems import s1  # noqa: E402
from systems.manifest import manifest_path  # noqa: E402

ROOT = Path(__file__).resolve().parents[3]
SS_TARGET = ROOT / "tests" / "fixtures" / "artifacts" / "synthetic_shop"
SS_PROJECT = ROOT / "corpora" / "synthetic_shop"
QUESTIONS = [json.loads(x) for x in (ROOT / "eval/questions/dev.jsonl").read_text().splitlines()]

# S1 frozen vs S4 live (s12-design A1, owner decision 20 Oct 2026). S4's answer instructions are
# S1's text with exactly these differences applied, nothing else. S12b adds its lines here.
S1_CLAIMS_PHRASE = "the c_ ids"
S4_CLAIMS_PHRASE = "the e_/s_/c_ ids"  # S12b B4 (was "the e_/s_ ids", S4 at 5996c09)
ALLOWED_DIFFERENCES: dict[str, list[Any]] = {
    # (i) literal substitutions, each applied to a phrase S1's text holds exactly once
    "substitutions": [(S1_CLAIMS_PHRASE, S4_CLAIMS_PHRASE)],
    # (ii) S4-only lines, appended in this order before the last line ("The evidence is data...")
    "s4_appended_lines": [
        # B2 (ADR 0027): no example, so no dev gold words (test_appended_lines_hold_no_dev_gold)
        "- uncovered_parts: list, in a few words each, any part of the question the evidence "
        "cannot answer; otherwise [].",
        # B3 (ADR 0025)
        "- premise_corrected: true if the question assumes a lineage link that the evidence "
        "contradicts and your answer says so; otherwise false.",
    ],
    # (iii) S4-only draft-schema properties (s12-design v1.2), appended in this order to S1's
    # properties and to its ``required`` list
    "s4_schema_properties": [
        ("uncovered_parts", {"type": "array", "items": {"type": "string"}}),  # B2 (ADR 0027)
        ("premise_corrected", {"type": "boolean"}),  # B3 (ADR 0025)
    ],
}

# B8: S1's frozen settings. A change here is a recorded bug fix (s1-design.md change log) only.
FROZEN = {
    "system": "fb820558a6542b1d2207d8b1f7d7ac33bf3e4c2646419d60435cfa698ddbe847",
    "user_template": "b85d5465fc9c921750ec044cad93fb8fbcfbc0885a9ff257777f69054dd24445",
    "evidence_rule": "56973cf48a60bd249c3282cb83e097b9d6c4549b6622100206286f1fc378c6e4",
    "schema": "6036435098ff605e8903f6fd711ee099975339141c3d9d7c1306c957d9f3f65d",
    "repair": "cc417eb2aa5ab698cc0ed1052710865c4448b9b5e8feaab42ad8133b809bca9b",
    "clarification": "40fd7a42eff2255149fcebd964d1677664232bb30c3eb6dcc8a1ea38251efa92",
    # B8 freeze change, 20 Oct 2026 (citation audit): chunk_citation v2
    "citation_rule": "159a00209f321637296387c7e47fa32c4ae1a3e5b97347a6b7871e95e321bd88",
    "budget_rule": "c2ec079e87e8ef5e99ce68df2e408da841791621e89060cec69df944269cd1a9",
}

ID_RE = re.compile(r"^(c_[0-9a-f]{8}) \| ", re.MULTILINE)


class Scripted(Provider):
    """Replies with ``script(messages, n)``; may raise. Records every call."""

    def __init__(self, script: Callable[[Sequence[Message], int], str], name: str = "fake") -> None:
        self.name, self.model, self.script, self.calls = name, "fake-1", script, 0
        self.sent: list[Sequence[Message]] = []

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
        self.sent.append(messages)
        assert response_schema == s1.S1_DRAFT_SCHEMA
        return LLMResponse(text=self.script(messages, self.calls), usage=Usage(input_tokens=9))


def shown_ids(messages: Sequence[Message]) -> list[str]:
    return ID_RE.findall(messages[-1].content if messages[-1].role == "user" else "")


def draft(**kw: Any) -> str:
    base: dict[str, Any] = {
        "answer_text": "It comes from raw_payments.amt.",
        "claims": [],
        "confidence": "high",
        "refused": False,
        "refusal_reason": None,
        "reach_verdict": None,
        "clarification_candidates": [],
    }
    return json.dumps({**base, **kw})


def cite_first(messages: Sequence[Message], n: int) -> str:
    ids = shown_ids(messages[:2])
    return draft(claims=[{"text": "raw_payments.amt feeds it.", "ids": [ids[0], "c_00000000"]}])


@pytest.fixture(scope="module")
def index(tmp_path_factory: pytest.TempPathFactory) -> tuple[LineageGraph, SearchIndex]:
    # Building an index needs the retrieval extra: the tests that use it skip without it (CI
    # runs them in the retrieval job); the rest of this file needs no extra.
    pytest.importorskip("bm25s")
    pytest.importorskip("numpy")
    tmp = tmp_path_factory.mktemp("s1idx")
    graph = build_graph_from_artifacts(SS_TARGET)[0]
    gfile = tmp / "graph.json"
    graph.save(gfile)
    idx, _ = SearchIndex.open(
        graph=graph,
        graph_file=gfile,
        target_dir=SS_TARGET,
        project_dir=SS_PROJECT,
        index_dir=tmp / "index",
        embedder=FakeEmbedder(),
    )
    return graph, idx


def runner(index: tuple[LineageGraph, SearchIndex], prov: Provider, tmp: Path) -> s1.S1Runner:
    client = LLMClient(
        prov,
        ResponseCache(tmp / "cache.sqlite"),
        QuotaCounter(tmp / "quota.sqlite", {prov.name: None}),
        RateLimiter(None),
    )
    return s1.S1Runner(client, index[1], index[0], SS_PROJECT)


# -- a run, records, manifest ----------------------------------------------------------------


def test_fake_run_writes_records_and_manifest(index: Any, tmp_path: Path) -> None:
    r = runner(index, Scripted(cite_first), tmp_path)
    qs = QUESTIONS[:4]
    records = s1.run(r, qs)
    assert [rec.run_id for rec in records] == [f"s1-{q['id']}" for q in qs]
    path = tmp_path / "out" / "s1-fake-1-dev.jsonl"
    s1.write_records(records, path)
    man = s1.manifest(records, path, r, "index reused")
    mpath = s1.write_manifest(path, man)
    assert mpath == manifest_path(path)

    loaded = [json.loads(x) for x in path.read_text().splitlines()]
    for rec in loaded:
        assert RunRecord.model_validate(rec).model_dump(mode="json") == rec  # round trip
        assert Answer.model_validate(rec["final_answer"]).answer_text
        assert rec["project"] == "corpora/synthetic_shop"  # relative (no local paths)
        assert rec["tokens"]["llm_calls"] == 1 and rec["stop_reason"] == "answered"
        M.from_s1_record(rec)  # the metrics adapter accepts it

    m = json.loads(mpath.read_text())
    assert m["system"] == "s1-fake-1" and m["record_count"] == 4
    assert m["required"] == [q["id"] for q in qs]
    assert m["prompt_sha256"] == s1.frozen_hashes()
    assert m["budget"] == {
        "cap": 3000,
        "repair_reserve": 200,
        "fill_rule": "skip_and_pack",
        "k_ceiling": None,
        "overhead_est_tokens": m["budget"]["overhead_est_tokens"],
    }
    ret = m["retrieval"]
    assert (ret["mode"], ret["rrf_k"], ret["per_list_depth"], ret["candidates"]) == (
        "hybrid",
        60,
        100,
        200,
    )
    assert ret["kinds"] == "all (model, column, doc)" and ret["query"] == "raw question text"
    assert ret["embedder"]["model"] == "fake" and ret["index_key"]["chunker_version"] == 1
    assert ret["index_status"] == "index reused" and ret["citation_rule"] == s1.CITATION_RULE
    assert str(Path.home()) not in mpath.read_text() + path.read_text()


def test_records_are_cache_stable(index: Any, tmp_path: Path) -> None:
    prov = Scripted(cite_first)
    r = runner(index, prov, tmp_path)
    first = s1.run(r, QUESTIONS[:2])
    second = s1.run(r, QUESTIONS[:2])
    assert prov.calls == 2  # the re-run is served from the cache
    assert all(rec.tokens["cached_calls"] == 1 for rec in second)
    assert [a.final_answer for a in first] == [b.final_answer for b in second]


# -- budget (B2) -----------------------------------------------------------------------------


def test_budget_fits_with_the_repair_reserve(index: Any, tmp_path: Path) -> None:
    prov = Scripted(cite_first)
    rec = runner(index, prov, tmp_path).ask(QUESTIONS[0]["question"], "s1-x")
    ev = rec.evidence
    assert ev["est_tokens"] <= 3000 - 200 == ev["budget_limit"]
    assert ev["unused_budget_tokens"] == ev["budget_limit"] - ev["est_tokens"] >= 0
    assert ev["k_used"] == len(ev["ids"]) == len(ev["ranks"]) > 0
    assert ev["ranks"] == sorted(ev["ranks"]) and not set(ev["ranks"]) & set(ev["skipped_ranks"])
    assert ev["k_used"] + len(ev["skipped_ranks"]) == ev["candidates"]
    assert ev["stop"] == ("budget_full" if ev["skipped_ranks"] else "candidates_exhausted")
    # the one repair call always fits: the sent prompt plus the repair turn (no echo)
    sent = list(prov.sent[0])
    repair = Message(role="user", content=s1.REPAIR.format(error="x" * 300))
    assert s1.est([*sent, repair]) <= 3000


def test_skip_and_pack_skips_a_big_chunk_and_keeps_going(index: Any) -> None:
    chunks = index[1].chunks
    big = max(chunks, key=lambda c: len(c.text))
    small = sorted(chunks, key=lambda c: len(c.text))[:3]
    q = "q"
    base = s1.est(s1.messages(q, []))
    with_small = s1.est(s1.messages(q, [s1.render_chunk(c, SS_PROJECT) for c in small]))
    cap = with_small + s1.REPAIR_RESERVE  # room for the three small chunks, not the big one
    p = s1.pack(q, [small[0], big, small[1], small[2]], SS_PROJECT, cap)
    assert [r for r, _ in p.shown] == [1, 3, 4] and p.skipped == [2]
    assert p.stop == "budget_full" and p.overhead == base and p.est_tokens == with_small
    everything = s1.pack(q, small, SS_PROJECT, 3000)
    assert everything.stop == "candidates_exhausted" and everything.skipped == []


# -- evidence: no graph facts (B1) -----------------------------------------------------------


def test_prompt_holds_chunk_fields_only(index: Any, tmp_path: Path) -> None:
    prov = Scripted(cite_first)
    r = runner(index, prov, tmp_path)
    recs = [r.ask(q["question"], "s1-x") for q in QUESTIONS[:6]]
    by_id = {c.id: c for c in index[1].chunks}
    for rec, msgs in zip(recs, prov.sent, strict=True):
        user = msgs[-1].content
        evidence = user.split("<evidence>\n", 1)[1].rsplit("\n</evidence>", 1)[0]
        # exactly the shown chunks, rendered from chunk fields, in rank order
        rendered = [s1.render_chunk(by_id[i], SS_PROJECT) for i in rec.evidence["ids"]]
        assert evidence == "\n\n".join(rendered)
        assert "direct_inputs" not in evidence and "in_catalog" not in evidence
        assert '"graph"' not in evidence


def test_evidence_header_shows_the_seed_header_citation(index: Any) -> None:
    seed = next(c for c in index[1].chunks if c.file.endswith(".csv"))
    assert s1.render_chunk(seed, SS_PROJECT).split("\n", 1)[0] == (
        f"{seed.id} | {seed.file}:1-1 | {seed.title}"
    )


# -- citations (B4) --------------------------------------------------------------------------


def test_citations_come_only_from_the_ledger(index: Any, tmp_path: Path) -> None:
    seed = next(c for c in index[1].chunks if c.file.endswith(".csv"))
    model = next(c for c in index[1].chunks if c.kind == "model")
    ledger = s1.S1Ledger(index[0], SS_PROJECT, {seed.id: seed, model.id: model})
    d = s1.S1Draft.model_validate_json(
        draft(claims=[{"text": "t", "ids": [seed.id, model.id, "c_deadbeef", "e_01234567"]}])
    )
    a = s1.build_answer(d, ledger, "q")
    assert a.claims[0].chunk_ids == [seed.id, model.id, "c_deadbeef"]  # unknown id kept
    assert a.claims[0].edge_ids == ["e_01234567"]  # kept too; M7 scores it uncited
    assert set(a.citations) == {seed.id, model.id}
    assert (a.citations[seed.id].line_start, a.citations[seed.id].line_end) == (1, 1)
    assert a.citations[seed.id].level == "line"
    assert (a.citations[model.id].file, a.citations[model.id].line_start) == (
        model.file,
        model.line_start,
    )


def test_unshown_chunk_gets_no_citation(index: Any, tmp_path: Path) -> None:
    def cite_unshown(messages: Sequence[Message], n: int) -> str:
        shown = set(shown_ids(messages))
        other = next(c.id for c in index[1].chunks if c.id not in shown)
        return draft(claims=[{"text": "t", "ids": [other]}])

    rec = runner(index, Scripted(cite_unshown), tmp_path).ask(QUESTIONS[0]["question"], "s1-x")
    assert rec.final_answer is not None
    assert rec.final_answer["citations"] == {} and rec.final_answer["claims"][0]["chunk_ids"]


# -- verdict, clarification, refusal (B5, ADR 0024) ------------------------------------------


def test_verdict_and_clarification(index: Any, tmp_path: Path) -> None:
    yes = runner(index, Scripted(lambda m, n: draft(reach_verdict="yes")), tmp_path / "a")
    a = Answer.model_validate(yes.ask("Does a reach b?", "s1-x").final_answer)
    assert (a.reach_verdict, a.reach_verdict_source) == ("yes", "llm")
    cands = ["fct_customer_cohorts.order_month", "fct_segment_monthly.order_month"]
    clar = runner(
        index,
        Scripted(lambda m, n: draft(clarification_candidates=cands, claims=[])),
        tmp_path / "b",
    )
    rec = clar.ask("Where does order month come from?", "s1-x")
    a = Answer.model_validate(rec.final_answer)
    assert a.clarification is not None and a.clarification.candidates == cands
    assert a.claims == [] and rec.clarification == a.clarification.model_dump()
    pred = M.from_s1_record(rec.model_dump(mode="json"))
    assert pred.kind == "clarification"


def test_refusal_reads_the_schema_field(index: Any, tmp_path: Path) -> None:
    r = runner(
        index,
        Scripted(lambda m, n: draft(refused=True, refusal_reason="not in the evidence")),
        tmp_path,
    )
    a = Answer.model_validate(r.ask("q", "s1-x").final_answer)
    assert a.refused and a.refusal_reason == "not in the evidence"


# -- repair and retry (B6) -------------------------------------------------------------------


def test_repair_counts_two_calls(index: Any, tmp_path: Path) -> None:
    prov = Scripted(lambda m, n: "not json" if n == 1 else cite_first(m, n))
    rec = runner(index, prov, tmp_path).ask(QUESTIONS[0]["question"], "s1-x")
    assert [s.phase for s in rec.steps] == ["answer", "repair"]
    assert rec.tokens["llm_calls"] == 2 and rec.stop_reason == "repaired"
    assert prov.sent[1][-1].content.startswith("That reply was not valid JSON for the schema:")
    assert not Answer.model_validate(rec.final_answer).refused


def test_second_json_failure_refuses(index: Any, tmp_path: Path) -> None:
    rec = runner(index, Scripted(lambda m, n: "{}"), tmp_path).ask("q", "s1-x")
    a = Answer.model_validate(rec.final_answer)
    assert a.refused and "invalid answer JSON" in (a.refusal_reason or "")
    assert rec.tokens["llm_calls"] == 2 and rec.stop_reason == "invalid_json"


def test_one_retry_on_a_retryable_provider_error(index: Any, tmp_path: Path) -> None:
    def flaky(messages: Sequence[Message], n: int) -> str:
        if n == 1:
            raise ProviderError("busy", status_code=503, retryable=True)
        return cite_first(messages, n)

    rec = runner(index, Scripted(flaky), tmp_path).ask(QUESTIONS[0]["question"], "s1-x")
    assert rec.tokens["llm_calls"] == 2 and rec.steps[0].error == "busy"
    assert rec.stop_reason == "answered"


# -- prompt parity (B3) and freeze (B8) ------------------------------------------------------


def s4_from_s1(text: str) -> str:
    for old, new in ALLOWED_DIFFERENCES["substitutions"]:
        assert text.count(old) == 1, f"{old!r} must occur exactly once in S1's text"
        text = text.replace(old, new)
    lines = text.splitlines()
    return "\n".join([*lines[:-1], *ALLOWED_DIFFERENCES["s4_appended_lines"], lines[-1]])


def s4_schema_from_s1(schema: dict[str, Any]) -> dict[str, Any]:
    added = ALLOWED_DIFFERENCES["s4_schema_properties"]
    assert not {name for name, _ in added} & set(schema["properties"])
    return {
        **schema,
        "properties": {**schema["properties"], **dict(added)},
        "required": [*schema["required"], *(name for name, _ in added)],
    }


def test_s1_frozen_vs_s4_live() -> None:
    assert prompts.ANSWER_SYSTEM == s4_from_s1(s1.S1_SYSTEM)  # byte-equal, whole text
    assert prompts.ANSWER_REPAIR == s1.REPAIR
    assert prompts.answer_user("Q", "E", []) == s1.USER_TEMPLATE.format(question="Q", evidence="E")
    want = s4_schema_from_s1(s1.S1_DRAFT_SCHEMA)  # A2's byte-equality, plus (iii) only
    assert DRAFT_SCHEMA == want
    assert json.dumps(DRAFT_SCHEMA) == json.dumps(want)  # same key order (Ollama's grammar)
    assert s1.frozen_hashes() == FROZEN  # S1 itself did not move


def test_a_drifted_s4_line_fails_the_parity_check() -> None:
    drifted = prompts.ANSWER_SYSTEM.replace("1-4 plain sentences", "1-3 plain sentences")
    assert drifted != s4_from_s1(s1.S1_SYSTEM)


def test_frozen_settings_unchanged() -> None:
    assert s1.frozen_hashes() == FROZEN
    assert (s1.MODE, s1.KINDS, s1.CANDIDATES, s1.FILL_RULE, s1.K_CEILING) == (
        "hybrid",
        None,
        200,
        "skip_and_pack",
        None,
    )
    assert s1.REPAIR_RESERVE == 200


# -- cloud gate ------------------------------------------------------------------------------


def test_is_cloud() -> None:
    from dlens.agent.llm.ollama import OllamaProvider

    assert not s1.is_cloud(OllamaProvider(client=object()))
    local = OpenAICompatProvider("openai", "http://localhost:11434/v1", "m-1", client=object())  # type: ignore[arg-type]
    remote = OpenAICompatProvider(
        "openai",
        "https://x.example/v1",
        "m-1",
        "K",
        env={"K": "k"},
        client=object(),  # type: ignore[arg-type]
    )
    assert not s1.is_cloud(local) and s1.is_cloud(remote)
    assert s1.is_cloud(Scripted(cite_first, name="gemini"))


def test_main_refuses_a_cloud_provider_without_allow_cloud(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    for k, v in {
        "DLENS_PROVIDER": "openai",
        "DLENS_OPENAI_BASE_URL": "https://x.example/v1",
        "DLENS_OPENAI_MODEL": "m-1",
        "DLENS_OPENAI_KEY_ENV": "S1_TEST_KEY",
        "S1_TEST_KEY": "k",
        "DLENS_OPENAI_DAILY_BUDGET": "5",
        "DLENS_CACHE_DIR": str(tmp_path / "c"),
        "DLENS_STATE_DIR": str(tmp_path / "s"),
    }.items():
        monkeypatch.setenv(k, v)
    monkeypatch.setattr(s1, "open_index", lambda *a: pytest.fail("index opened before the gate"))
    assert s1.main(["--out", str(tmp_path / "out"), "--limit", "1"]) == 2
    assert "--allow-cloud" in capsys.readouterr().err
    assert not (tmp_path / "out").exists()
