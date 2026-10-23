"""S13c (owner decision): check_s0_stable compares with the newest versioned S0 baseline under
eval/runs/s0/baseline/<session>/ by default, and with the pilot records with --pilot; the pilot
S0 records are never rewritten. The s13c baseline's manifests record why it exists."""

import importlib.util
import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3]
SCRIPT = ROOT / "scripts" / "check_s0_stable.py"
spec = importlib.util.spec_from_file_location("check_s0_stable_b", SCRIPT)
assert spec is not None and spec.loader is not None
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)


def test_newest_baseline_is_the_default_and_pilot_is_a_flag(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    pilot = tmp_path / "s0"
    for name in ("s13c", "s14", "s13d"):
        (pilot / "baseline" / name).mkdir(parents=True)
    monkeypatch.setattr(mod, "COMMITTED", pilot)
    monkeypatch.setattr(mod, "BASELINES", pilot / "baseline")
    assert mod.reference() == pilot / "baseline" / "s14"
    assert mod.reference(pilot=True) == pilot


def test_no_baseline_means_the_pilot_records(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(mod, "COMMITTED", tmp_path)
    monkeypatch.setattr(mod, "BASELINES", tmp_path / "baseline")
    assert mod.reference() == tmp_path


def test_the_s13c_baseline_is_committed_and_labelled() -> None:
    base = ROOT / "eval" / "runs" / "s0" / "baseline" / "s13c"
    names = {"s0-gold-dev", "s0-linked-dev", "s0-linked-hybrid-dev"}
    for n in names:
        assert (base / f"{n}.jsonl").is_file()
        man = json.loads((base / f"{n}.manifest.json").read_text())
        assert man["baseline"].startswith("baseline after S13c L1/L2")
    assert mod.reference() == base  # the repo's default today
