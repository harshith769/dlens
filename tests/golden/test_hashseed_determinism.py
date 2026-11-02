"""S15e (ADR 0030): engine output must not depend on PYTHONHASHSEED.

sqlglot builds a lineage node's ``downstream`` from a set, so the order paths are walked in
follows the hash seed. ``tied_two_branch`` has one upstream column reaching its output through
two branches of equal strength; each seed runs in its own interpreter, and every edge field
(expression and lines included) must be the same in all of them.
"""

import json
import os
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).parent
SEEDS = ("0", "1", "2", "3")

_DUMP = """
import json
from _harness import run_fixture
got = run_fixture("tied_two_branch")
print(json.dumps({
    "edges": sorted((e.model_dump(mode="json") for e in got.direct_edges), key=json.dumps),
    "indirect": sorted((e.model_dump(mode="json") for e in got.indirect_edges), key=json.dumps),
}, sort_keys=True))
"""


def _dump(seed: str) -> dict[str, object]:
    env = {**os.environ, "PYTHONHASHSEED": seed}
    out = subprocess.run(
        [sys.executable, "-c", _DUMP], cwd=HERE, env=env, check=True, capture_output=True, text=True
    )
    data: dict[str, object] = json.loads(out.stdout)
    return data


def test_tied_paths_give_the_same_edges_under_every_hash_seed() -> None:
    dumps = {seed: _dump(seed) for seed in SEEDS}
    first = dumps[SEEDS[0]]
    assert first["edges"], "the fixture produced no edges"
    for seed in SEEDS[1:]:
        assert dumps[seed] == first, f"PYTHONHASHSEED={seed} differs from {SEEDS[0]}"
