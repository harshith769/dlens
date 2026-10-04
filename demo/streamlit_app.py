"""Streamlit Community Cloud entrypoint for the public DLens demo.

Cloud installs demo/requirements.txt (next to this file, so it wins over the root uv.lock) and
runs this script from the repo root. The package is not installed: src/ goes on sys.path.
Demo mode is forced on: the app reads the prebuilt bundle in demo/, never dbt or target/.
"""

import os
import runpy
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
os.environ.setdefault("DLENS_DEMO", "1")
if str(ROOT / "src") not in sys.path:
    sys.path.insert(0, str(ROOT / "src"))

# run_path, not import: Streamlit re-runs this script on every interaction.
runpy.run_path(str(ROOT / "src" / "dlens" / "ui" / "app.py"), run_name="__main__")
