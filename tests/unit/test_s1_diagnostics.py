"""S1 diagnostics (S11 step 5, report only): health counts and the retrieval / LLM miss split."""

import sys
from pathlib import Path
from types import SimpleNamespace as NS
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))
import s1_diagnostics as D  # noqa: E402


def rec(qid: str, ids: list[str], ranks: list[int], **kw: Any) -> dict[str, Any]:
    seed = {"file": "seeds/raw.csv", "line_start": 1, "line_end": 1}
    claim = {"text": "t", "edge_ids": [], "chunk_ids": ["c_1", "c_zz"]}
    final = {"answer_text": "x", "refused": False, "clarification": None, "claims": [claim],
             "citations": {"c_1": seed}}  # fmt: skip
    steps = kw.pop("steps", [{"phase": "answer"}])
    return {
        "question": qid,
        "stop_reason": kw.pop("stop_reason", "answered"),
        "final_answer": {**final, **kw.pop("final", {})},
        "steps": steps,
        "evidence": {
            "ids": ids,
            "ranks": ranks,
            "k_used": len(ids),
            "candidates": 5,
            "unused_budget_tokens": 3,
            "stop": "budget_full",
        },  # fmt: skip
        "tokens": {
            "llm_calls": len(steps),
            "cached_calls": 0,
            "max_est_input": 2700,
            "sum_input": 2000,
            "sum_output": 90,
        },  # fmt: skip
        "timings": {"total_ms": 1000.0},
    }


def test_health_counts() -> None:
    records = [
        rec("a", ["c_1"], [1]),
        rec(
            "b",
            ["c_1"],
            [1],
            steps=[{"phase": "answer"}, {"phase": "repair"}],
            stop_reason="repaired",
        ),  # fmt: skip
        rec(
            "c",
            ["c_1"],
            [1],
            final={"refused": True, "claims": [], "citations": {}},
            stop_reason="invalid_json",
            steps=[{"phase": "answer"}, {"phase": "repair"}],
        ),  # fmt: skip
    ]
    h = D.health(records)
    assert h["answer_kinds"] == {"answered": 2, "refused": 1}
    assert (h["json_parse_failures_first_try"], h["repairs_succeeded"]) == (2, 1)
    assert h["json_failed_after_repair"] == 1 and h["llm_calls_total"] == 5
    assert (h["cited_ids"], h["uncited_ids"], h["seed_card_citations"]) == (4, 2, 2)


class Index:
    def __init__(self) -> None:
        self.chunks = [
            NS(id="c_t", kind="column", column="model.p.m.target"),
            NS(id="c_u", kind="column", column="model.p.m.other"),
            NS(id="c_x", kind="model", column=None),
        ]

    def search(self, q: str, **kw: Any) -> list[Any]:
        order = {"q1": ["c_t", "c_x"], "q2": ["c_x", "c_t"], "q3": ["c_x"]}[q]
        return [NS(chunk=next(c for c in self.chunks if c.id == i)) for i in order]


def test_retrieval_split() -> None:
    qs = [
        {"id": q, "question": q, "type": "trace", "wording": w, "target": "m.target"}
        for q, w in (("q1", "identifier"), ("q2", "description"), ("q3", "description"))
    ]
    records = {
        "q1": rec("q1", ["c_t"], [1]),  # card shown
        "q2": rec("q2", ["c_x"], [1]),  # card retrieved at rank 2, not shown
        "q3": rec("q3", ["c_x"], [1]),  # card not retrieved
    }
    rows = {q: {"metrics": {"fully_correct": 0.0}} for q in ("q1", "q2", "q3")}
    r = D.retrieval(records, qs, rows, Index())
    assert r["rank_check_mismatches"] == []
    status = {x["id"]: (x["status"], x["rank"]) for x in r["questions"]}
    assert status == {"q1": ("shown", 1), "q2": ("retrieved, not shown", 2),
                      "q3": ("not retrieved", None)}  # fmt: skip
    assert r["overall"] == {"with_card": 3, "card_shown": 1, "losses": 3, "retrieval_miss": 2,
                            "llm_miss": 1}  # fmt: skip
    assert r["by_wording"]["description"]["retrieval_miss"] == 2
