"""PreToolUse guard: exit 2 blocks the tool call.

- Blocks writes to the frozen benchmark files.
- Blocks reads of .env (not .env.example). Best-effort for Bash.
"""

import json
import re
import sys

FROZEN = re.compile(r"eval/questions/(test\.jsonl|external\.jsonl|test\.sha256|external\.sha256)$")
ENV_FILE = re.compile(r"(^|/)\.env$")
ENV_IN_CMD = re.compile(r"(^|[\s/'\"=<>])\.env($|[\s'\";|&<>])")
WRITE_TOOLS = {"Write", "Edit", "MultiEdit", "NotebookEdit"}


def block(msg: str) -> None:
    print(f"BLOCKED: {msg}", file=sys.stderr)
    sys.exit(2)


def main() -> None:
    data = json.load(sys.stdin)
    tool = data.get("tool_name", "")
    inp = data.get("tool_input", {}) or {}
    path = inp.get("file_path") or inp.get("notebook_path") or inp.get("path") or ""

    if tool in WRITE_TOOLS and FROZEN.search(path):
        block(f"{path} is a frozen benchmark file.")
    if tool == "Bash":
        cmd = inp.get("command", "")
        if re.search(r"eval/questions/(test|external)\.(jsonl|sha256)", cmd) and re.search(
            r"(>|\btee\b|\bsed\s+-i|\bmv\b|\bcp\b|\brm\b|\btruncate\b)", cmd
        ):
            block("command may modify frozen benchmark files.")
        if ENV_IN_CMD.search(cmd):
            block("commands touching .env are not allowed.")
    if tool in {"Read", "Grep", "Glob"} and ENV_FILE.search(path):
        block(".env must never be read.")


main()
