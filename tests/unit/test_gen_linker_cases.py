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


def test_no_match_cases_have_empty_gold_except_interpreted_ones():
    # The one exception is the owner's S09 trap-8 re-gold: an interpreted dotted near-miss.
    regolded = {c["id"]: c["gold"] for c in CASES if c["variant"] == "no_match" and c["gold"]}
    assert regolded == {"lk-no_match-026": ["stg_shipments.shipping_cost_usd"]}


def test_interpreted_no_match_follows_its_gold_column_split():
    # S09: the re-golded case moves to linker-dev, where its gold column's other cases are.
    case = next(c for c in CASES if c["id"] == "lk-no_match-026")
    same_gold = {c["split"] for c in CASES if c["gold"] == case["gold"]}
    assert case["split"] == "linker-dev" and same_gold == {"linker-dev"}


def test_v02_dev_targets_never_in_linker_test():
    dev = set(gl.V02_DEV_TARGETS)
    assert not [c for c in CASES if c["split"] == "linker-test" and set(c["gold"]) & dev]


def test_v02_dev_targets_are_the_pinned_twenty():
    v02 = gl.ROOT / "eval" / "questions" / "review" / "v02_dev.jsonl"
    targets = {json.loads(x)["target"] for x in v02.read_text().splitlines()}
    assert targets == set(gl.V02_DEV_TARGETS)


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
    done = gaps["resolved_s08"]
    mentions = {c["mention"] for c in CASES if c["variant"] == "linker_gap"}
    want = {g["id"] for g in [*done["exact_id_top1"], *gaps["exact_id_top1"]]}
    assert want | {f["query"] for f in done["fragile"]} == mentions


def test_collision_check_sees_weak_tokens():
    # bare "amount" reaches amt (abbreviation) and amount_usd (usd dropped): never a single gold
    assert B.collisions("amount", "amt") == ["amount_usd"]


def test_owner_drop_rules():
    assert all(len(c["gold"]) <= gl.MAX_GOLD for c in CASES)
    assert not {c["mention"].lower() for c in CASES} & gl.DROP_MENTIONS
