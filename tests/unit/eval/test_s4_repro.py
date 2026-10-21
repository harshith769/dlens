"""scripts/check_s4_repro.py: only the excluded fields may differ, and the second pass must be
fully cached."""

import importlib.util
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[3] / "scripts" / "check_s4_repro.py"
spec = importlib.util.spec_from_file_location("check_s4_repro", SCRIPT)
assert spec is not None and spec.loader is not None
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)


def rec(cached: bool, **kw: object) -> dict:
    return {
        "run_id": "uuid-1" if not cached else "uuid-2",
        "question_id": "dev-01",
        "started_at": "t1" if not cached else "t2",
        "timings": {"total_ms": 5.0 if not cached else 1.0},
        "steps": [
            {"phase": "tool", "cached": cached, "latency_ms": 9.0, "text": "a"},
            {"phase": "code", "results": []},
        ],
        "cache": "hit" if cached else "miss",
        "tokens": {"llm_calls": 1, "cached_calls": int(cached), "sum_input": 10},
        "final_answer": {"answer_text": "x"},
        **kw,
    }


def test_a_cached_second_pass_matches() -> None:
    assert mod.compare([rec(False)], [rec(True)]) == []


def test_any_other_difference_fails() -> None:
    other = rec(True, final_answer={"answer_text": "y"})
    assert mod.compare([rec(False)], [other]) == [
        "dev-01: differs outside the excluded fields in ['final_answer']"
    ]
    tokens = rec(True)
    tokens["tokens"]["sum_input"] = 11
    assert mod.compare([rec(False)], [tokens]) != []


def test_an_uncached_call_in_the_second_pass_fails() -> None:
    assert mod.compare([rec(False)], [rec(False)]) != []
    assert "uncached" in mod.compare([rec(False)], [rec(False)])[0]


def test_count_and_order() -> None:
    assert mod.compare([rec(False)], []) == ["record count 1 != 0"]
    assert "order" in mod.compare([rec(False)], [rec(True, question_id="dev-02")])[0]
