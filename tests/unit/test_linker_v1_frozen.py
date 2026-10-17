"""eval/linker/v1.py is the frozen linker v1 the S08 report compares against: never edited."""

import hashlib
import subprocess
from pathlib import Path

ROOT = Path(__file__).parents[2]
V1 = ROOT / "eval" / "linker" / "v1.py"
V1_SHA256 = "492e1e519d5b521b8db9da03007326c04f80484708a40b7d2e1d878635e46734"


def test_v1_copy_is_unchanged():
    assert hashlib.sha256(V1.read_bytes()).hexdigest() == V1_SHA256


def test_v1_copy_matches_the_v1_commit():
    try:
        old = subprocess.run(
            ["git", "show", "66a3f1e:src/dlens/agent/tools/entity.py"],
            cwd=ROOT,
            capture_output=True,
            text=True,
            check=True,
        ).stdout
    except (OSError, subprocess.CalledProcessError):  # no git history (sdist): the hash suffices
        return
    body = V1.read_text().split("\n", 2)[2]
    assert body == old
