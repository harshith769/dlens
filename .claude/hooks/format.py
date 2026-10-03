"""PostToolUse: run ruff format + ruff check on edited Python files.

Never blocks: any formatter problem is a warning on stderr and the hook exits 0. (Exit 2 shows
only stderr, and ruff writes its diagnostics to stdout, so blocking gave an empty error.)
F401 is left unfixed so an import added in one edit isn't deleted before its use arrives.
"""

import json
import subprocess
import sys

TIMEOUT_S = 30


def warn(msg: str) -> None:
    print(f"format hook: {msg.rstrip()}", file=sys.stderr)


def run(args: list[str]) -> None:
    result = subprocess.run(args, capture_output=True, text=True, check=False, timeout=TIMEOUT_S)
    if result.returncode:
        warn(f"`{' '.join(args[1:4])}` exited {result.returncode}\n{result.stdout}{result.stderr}")


def main() -> None:
    data = json.load(sys.stdin)
    path = (data.get("tool_input") or {}).get("file_path", "")
    if not path.endswith(".py"):
        return
    run(["uv", "run", "ruff", "format", path])
    run(["uv", "run", "ruff", "check", "--fix", "--unfixable", "F401", path])


try:
    main()
except (json.JSONDecodeError, AttributeError, OSError, subprocess.TimeoutExpired) as e:
    warn(f"skipped: {type(e).__name__}: {e}")
sys.exit(0)
