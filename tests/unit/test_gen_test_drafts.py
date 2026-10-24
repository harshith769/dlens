"""scripts/gen_test_drafts.py: the committed test drafts are reproducible from the gold spec.

Assertions compare hashes and counts only, so a failure never prints draft text.
"""

import hashlib
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).parents[2]
sys.path.insert(0, str(ROOT / "scripts"))
import gen_test_drafts as gt  # noqa: E402


def sha(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()


def test_committed_drafts_are_fresh():
    assert sha(gt.render(gt.build())) == sha(gt.OUT.read_text()), "run gen_test_drafts.py"


def test_generator_never_loads_the_graph_parser_or_linker():
    code = (
        "import sys; sys.path.insert(0, 'scripts'); import gen_test_drafts as gt; gt.build(); "
        "bad = [m for m in sys.modules if m.startswith(('dlens.graph', 'dlens.lineage', "
        "'dlens.agent', 'dlens.retrieval'))]; print(len(bad)); sys.exit(1 if bad else 0)"
    )
    r = subprocess.run([sys.executable, "-c", code], cwd=ROOT, capture_output=True, text=True)
    assert r.returncode == 0, f"{r.stdout.strip()} forbidden modules loaded"


def test_unit_slots_are_interpreted_near_misses():
    rows = gt.build()
    interp = [q for q in rows if "interpretation" in q["gold"]]
    assert len(interp) == 3
    for q in interp:
        assert q["gold"]["interpretation"]["column"] == q["target"]
        assert q["mention"] == q["gold"]["interpretation"]["text"] != q["target"]
