"""PreToolUse gate: a Bash `git commit` runs only if `make lint && make test` both exit 0.

Exit 2 blocks the tool call and shows the tail of the failing output. Every other Bash command
passes through untouched (no make run).

The gate fires only when `git commit` is an actual command: at command position (the start, or
after `&&`, `||`, `;`, `|`, `&`, `(` or a newline), after optional VAR=value assignments and git's
global options (`-C dir`, `-c k=v`, `--git-dir=...`). Heredoc bodies and quoted strings never
trigger it. If the command can't be tokenised (unbalanced quotes), it falls back to a plain text
match, so an unclear command is gated rather than let through.

Accepted limitation (owner, S09): the gate runs once, before the whole Bash command. In
`rm x && git commit`, the checks run while `x` still exists; they see the working tree as it is
before the command, not the tree the commit will record.
"""

import json
import os
import re
import shlex
import subprocess
import sys

TEXT_FALLBACK = re.compile(r"\bgit\s+(?:-[Cc]\s+\S+\s+)*commit(?![\w-])")
HEREDOC = re.compile(r"<<-?\s*(['\"]?)([A-Za-z_][A-Za-z0-9_]*)\1")
SEPARATORS = {"&&", "||", ";", "|", "&", "(", ")", ";;", "|&"}
ASSIGNMENT = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*=")
GIT_OPTS_WITH_ARG = {"-C", "-c", "--git-dir", "--work-tree", "--namespace"}
TAIL_LINES = 40


def strip_heredocs(cmd: str) -> str:
    """Drop heredoc bodies (the lines after a `<<WORD` line, up to the line that is WORD)."""
    out: list[str] = []
    ends: list[str] = []
    for line in cmd.split("\n"):
        if ends:
            if line.strip() == ends[0]:
                ends.pop(0)
            continue
        out.append(line)
        ends += [m.group(2) for m in HEREDOC.finditer(line)]
    return "\n".join(out)


def runs_git_commit(cmd: str) -> bool:
    text = strip_heredocs(cmd).replace("\n", " ; ")
    try:
        lex = shlex.shlex(text, posix=True, punctuation_chars=True)
        lex.whitespace_split = True
        tokens = list(lex)
    except ValueError:
        return bool(TEXT_FALLBACK.search(cmd))
    at_start = True
    i = 0
    while i < len(tokens):
        tok = tokens[i]
        if tok in SEPARATORS:
            at_start = True
            i += 1
            continue
        if not at_start or ASSIGNMENT.match(tok):
            i += 1
            continue
        at_start = False
        i += 1
        if tok != "git":
            continue
        while i < len(tokens) and tokens[i].startswith("-"):
            i += 2 if tokens[i] in GIT_OPTS_WITH_ARG else 1
        if i < len(tokens) and tokens[i] == "commit":
            return True
    return False


def main() -> None:
    data = json.load(sys.stdin)
    if data.get("tool_name") != "Bash":
        return
    cmd = (data.get("tool_input") or {}).get("command", "")
    if not runs_git_commit(cmd):
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
