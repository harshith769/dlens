"""The S0 stability comparison (scripts/check_s0_stable.py): only timings.total_ms may differ."""

import importlib.util
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[3] / "scripts" / "check_s0_stable.py"
spec = importlib.util.spec_from_file_location("check_s0_stable", SCRIPT)
assert spec is not None and spec.loader is not None
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)


def rec(ms: float, **kw: object) -> dict:
    return {"run_id": "s0-gold-dev-01", "timings": {"total_ms": ms, "x": 1}, "answer": "a", **kw}


def test_only_the_excluded_field_may_differ() -> None:
    assert mod.EXCLUDED == ("timings", "total_ms")
    assert mod.compare([rec(1.0)], [rec(9.5)]) == []
    assert mod.compare([rec(1.0)], [rec(1.0, answer="b")]) != []
    other = rec(1.0)
    other["timings"]["x"] = 2  # a sibling timing is not excluded
    assert mod.compare([rec(1.0)], [other]) != []
    assert mod.compare([rec(1.0)], []) == ["record count 1 != 0"]
