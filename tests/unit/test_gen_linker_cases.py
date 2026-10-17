"""scripts/gen_linker_cases.py: the linker set is fresh, gold is from the spec, the split holds."""

import importlib.util
import json
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).parents[2]
_spec = importlib.util.spec_from_file_location(
    "gen_linker_cases", ROOT / "scripts" / "gen_linker_cases.py"
)
assert _spec and _spec.loader
gl = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(gl)

FILES, B = gl.build()
CASES = [json.loads(line) for line in FILES["cases.jsonl"].splitlines()]


def test_files_on_disk_are_fresh():
    for name, text in FILES.items():
        assert (gl.OUT / name).read_text() == text, (
            f"{name} is stale: run scripts/gen_linker_cases.py"
        )


def test_every_gold_id_is_a_spec_column():
    ids = set(B.ids)
    assert all(g in ids for c in CASES for g in c["gold"])


def test_mentions_are_unique_and_ids_stable():
    assert len({c["mention"].lower() for c in CASES}) == len(CASES)
    assert len({c["id"] for c in CASES}) == len(CASES)


def test_no_match_cases_have_empty_gold():
    assert all(c["gold"] == [] for c in CASES if c["variant"] == "no_match")


def test_dev_targets_never_in_linker_test():
    dev = {json.loads(line)["target"] for line in gl.DEV.read_text().splitlines()}
    assert not [c for c in CASES if c["split"] == "linker-test" and set(c["gold"]) & dev]


def test_split_is_by_gold_column():
    split_of: dict[str, set[str]] = {}
    for c in CASES:
        if c["gold"]:
            split_of.setdefault(c["gold"][0], set()).add(c["split"])
    assert all(len(s) == 1 for s in split_of.values())


def test_each_phrase_rule_has_three_cases_and_two_in_test():
    rules = Counter(c["rule"] for c in CASES if c["variant"] == "phrase")
    test = Counter(
        c["rule"] for c in CASES if c["variant"] == "phrase" and c["split"] == "linker-test"
    )
    assert set(rules) == {"P1", "P2", "P3", "P4"}
    assert all(n >= 3 for n in rules.values()) and all(test[r] >= 2 for r in rules)


def test_every_linker_gap_is_a_case():
    import yaml

    gaps = yaml.safe_load(gl.GAPS.read_text())
    mentions = {c["mention"] for c in CASES if c["variant"] == "linker_gap"}
    assert {g["id"] for g in gaps["exact_id_top1"]} | {
        f["query"] for f in gaps["fragile"]
    } == mentions


def test_collision_check_sees_weak_tokens():
    # bare "amount" reaches amt (abbreviation) and amount_usd (usd dropped): never a single gold
    assert B.collisions("amount", "amt") == ["amount_usd"]


def test_owner_drop_rules():
    assert all(len(c["gold"]) <= gl.MAX_GOLD for c in CASES)
    assert not {c["mention"].lower() for c in CASES} & gl.DROP_MENTIONS
