"""Regenerate the "Construct support" table in docs/explain/lineage.md from the golden fixtures.

Run: uv run python scripts/gen_support_matrix.py   (add --check to fail if the doc is stale)
"""

import sys
from pathlib import Path

ROOT = Path(__file__).parents[1]
sys.path.insert(0, str(ROOT / "tests" / "golden"))

from _harness import MATRIX_END, MATRIX_START, support_matrix_md  # noqa: E402

DOC = ROOT / "docs" / "explain" / "lineage.md"


def rendered() -> str:
    text = DOC.read_text()
    head, rest = text.split(MATRIX_START)
    _, tail = rest.split(MATRIX_END)
    return f"{head}{MATRIX_START}\n{support_matrix_md()}\n{MATRIX_END}{tail}"


if __name__ == "__main__":
    new = rendered()
    if "--check" in sys.argv:
        sys.exit(0 if new == DOC.read_text() else 1)
    DOC.write_text(new)
