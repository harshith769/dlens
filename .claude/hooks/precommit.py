"""PreToolUse gate: a Bash `git commit` runs only if `make lint && make test` both exit 0.

Exit 2 blocks the tool call and shows the tail of the failing output. Every other Bash command
passes through untouched (no make run).
"""

import json
import os
import re
import subprocess
import sys

GIT_COMMIT = re.compile(r"\bgit\s+(?:-[Cc]\s+\S+\s+)*commit(?![\w-])")
TAIL_LINES = 40


def main() -> None:
    data = json.load(sys.stdin)
    if data.get("tool_name") != "Bash":
        return
    cmd = (data.get("tool_input") or {}).get("command", "")
    if not GIT_COMMIT.search(cmd):
        return
    root = os.environ.get("CLAUDE_PROJECT_DIR") or os.getcwd()
    for target in ("lint", "test"):
        proc = subprocess.run(
            ["make", target], cwd=root, capture_output=True, text=True, check=False
        )
        if proc.returncode != 0:
            tail = "\n".join((proc.stdout + proc.stderr).splitlines()[-TAIL_LINES:])
            print(f"BLOCKED: `make {target}` failed; commit refused.\n{tail}", file=sys.stderr)
            sys.exit(2)


if __name__ == "__main__":
    main()
