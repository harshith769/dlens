"""Boot the public demo from its Cloud install and click a preset. No dbt, no Ollama, no key.

Usage (in a venv built ONLY from demo/requirements.txt, from the repo root):
    python scripts/demo_install_check.py

Fails if the heavy packages are installed or imported, if the app raises or shows an error, or
if the preset does not render. CI runs it in the "demo-install" job, so a stray dbt/torch import
fails CI instead of the live app.
"""

import importlib.util
import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
HEAVY = ("dbt", "torch", "sentence_transformers", "lancedb", "bm25s")


def main() -> int:
    installed = [m for m in HEAVY if importlib.util.find_spec(m) is not None]
    if installed:
        sys.exit(f"demo install is not light: {installed} installed")
    os.chdir(ROOT)
    os.environ["DLENS_DEMO"] = "1"
    state = tempfile.mkdtemp(prefix="dlens-demo-check-")
    os.environ["DLENS_DEMO_STATE_DIR"] = state  # never the real demo counter

    from streamlit.testing.v1 import AppTest

    at = AppTest.from_file(str(ROOT / "demo" / "streamlit_app.py"), default_timeout=60)
    at.run()
    problems = [str(e.value) for e in at.exception] + [e.value for e in at.error]
    presets = [b for b in at.button if b.key and b.key.startswith("preset-")]
    if problems or not presets:
        sys.exit(f"boot failed: {problems or 'no preset buttons'}")
    presets[0].click().run()
    problems = [str(e.value) for e in at.exception] + [e.value for e in at.error]
    shown = [m.value for m in at.markdown]
    if problems or not any("Precomputed with local" in m for m in shown):
        sys.exit(f"preset failed: {problems or 'no precomputed badge'}")
    imported = sorted({m.split(".")[0] for m in sys.modules} & set(HEAVY))
    if imported:
        sys.exit(f"heavy modules imported: {imported}")
    print(f"OK: demo booted, {len(presets)} presets, replayed {presets[0].key}; no {HEAVY}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
