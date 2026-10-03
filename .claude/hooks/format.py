"""PostToolUse: run ruff format + ruff check on edited Python files."""

import json
import subprocess
import sys

data = json.load(sys.stdin)
path = (data.get("tool_input") or {}).get("file_path", "")
if path.endswith(".py"):
    subprocess.run(["uv", "run", "ruff", "format", path], check=False)
    result = subprocess.run(["uv", "run", "ruff", "check", "--fix", path], check=False)
    sys.exit(2 if result.returncode else 0)
