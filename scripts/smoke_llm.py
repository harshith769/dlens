"""Live LLM smoke through LLMClient (cache, quota and rate limit included).

Usage:
    uv run python scripts/smoke_llm.py --provider ollama
    uv run --extra agent python scripts/smoke_llm.py --provider gemini --max-calls 3 --yes-spend-quota

ollama: the same prompt twice, the second must be a cache hit. Cache and quota go to a throwaway
temp dir.

gemini (the owner runs this; it spends free quota): up to --max-calls live calls (hard cap 10),
one per check (plain text, JSON schema, tool call), then a repeat of the first that must be a
free cache hit. Uses GEMINI_API_KEY / DLENS_GEMINI_MODEL from the environment (the DEV key; .env
is never read here) and the REAL dev quota counter, never the demo's. Prints the counter before
and after. Refuses without --yes-spend-quota, if the budget left is below --max-calls, or if the
state dir is the demo's. The LLM cache is a throwaway temp dir so every check is a real call.
"""

from __future__ import annotations

import argparse
import os
import sys
import tempfile
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path
from typing import Any

from dlens.agent.llm import LLMClient, LLMResponse, Message, ToolSpec, make_client
from dlens.agent.llm.config import quota_path

HARD_CAP = 10
GEMINI = "gemini"

OK = [Message(role="user", content="Reply with the single word: ok")]
CHECKS: list[tuple[str, list[Message], list[ToolSpec] | None, dict[str, Any] | None]] = [
    ("text", OK, None, None),
    (
        "json",
        [Message(role="user", content='Return {"word": "ok"} as JSON.')],
        None,
        {"type": "object", "properties": {"word": {"type": "string"}}, "required": ["word"]},
    ),
    (
        "tool",
        [Message(role="user", content="Call the echo tool with text 'ok'.")],
        [
            ToolSpec(
                name="echo",
                description="Echo text back.",
                parameters={
                    "type": "object",
                    "properties": {"text": {"type": "string"}},
                    "required": ["text"],
                },
            )
        ],
        None,
    ),
]


def demo_state_dir() -> Path:
    from dlens.ui.demo import state_dir

    return state_dir()


class CappedSend:
    """Wraps provider.send: raises before the (cap+1)-th live call ever leaves the machine."""

    def __init__(self, send: Callable[..., LLMResponse], cap: int):
        self.send, self.cap, self.calls = send, cap, 0

    def __call__(self, *args: Any, **kwargs: Any) -> LLMResponse:
        if self.calls >= self.cap:
            raise RuntimeError(f"hard cap: refusing live call {self.calls + 1} (max {self.cap})")
        self.calls += 1
        return self.send(*args, **kwargs)


def _counter(client: LLMClient) -> str:
    used = client.quota.used(GEMINI)
    left = client.quota.remaining(GEMINI)
    return f"used today {used}, left {left} of {client.quota.budgets.get(GEMINI)}"


def smoke_gemini(
    max_calls: int,
    env: Mapping[str, str],
    factory: Callable[[str, Mapping[str, str]], LLMClient] = make_client,
) -> int:
    if Path(quota_path(env)).parent.resolve() == demo_state_dir().resolve():
        sys.exit("smoke_llm: the quota dir is the demo's; the smoke uses the DEV counter only.")
    with tempfile.TemporaryDirectory() as tmp:
        client = factory(GEMINI, {**env, "DLENS_CACHE_DIR": tmp})
        print(f"quota before: {_counter(client)}  (counter: {quota_path(env)})")
        left = client.quota.remaining(GEMINI)
        if left is not None and left < max_calls:
            print(f"refused: only {left} calls left today, --max-calls is {max_calls}")
            return 2
        capped = CappedSend(client.provider.send, max_calls)
        client.provider.send = capped  # type: ignore[method-assign]
        ok = True
        try:
            for name, msgs, tools, schema in CHECKS[:max_calls]:
                r = client.chat(msgs, tools, schema)
                calls = [(c.name, c.arguments) for c in r.tool_calls]
                print(f"{name}: cached={r.cached} usage={r.usage.model_dump()} text={r.text!r}")
                if calls:
                    print(f"  tool calls: {calls}")
                passed = bool(calls) if name == "tool" else bool(r.text)
                ok &= passed and not r.cached
            again = client.chat(OK)  # identical to the first check: must not touch quota
            print(f"repeat: cached={again.cached}")
            ok &= again.cached
        finally:
            print(f"live calls sent: {capped.calls} (cap {max_calls})")
            print(f"quota after:  {_counter(client)}")
    print("OK: gemini smoke passed." if ok else "FAILED: see the lines above.")
    return 0 if ok else 1


def smoke_ollama() -> int:
    with tempfile.TemporaryDirectory() as tmp:
        client = make_client("ollama", {"DLENS_CACHE_DIR": tmp, "DLENS_STATE_DIR": tmp})
        for attempt in (1, 2):
            r = client.chat(OK)
            print(f"call {attempt}: cached={r.cached} usage={r.usage.model_dump()} text={r.text!r}")
            assert ("<think>" not in r.text) and (r.cached == (attempt == 2))
    print("OK: live call worked and the repeat was served from cache.")
    return 0


def main(argv: Sequence[str] | None = None, env: Mapping[str, str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--provider", required=True, choices=["ollama", GEMINI])
    ap.add_argument("--max-calls", type=int, help=f"gemini: live calls allowed (1-{HARD_CAP})")
    ap.add_argument("--yes-spend-quota", action="store_true", help="gemini: confirm the spend")
    args = ap.parse_args(argv)
    if args.provider == "ollama":
        return smoke_ollama()
    if not args.yes_spend_quota:
        sys.exit("smoke_llm: gemini spends free quota; add --yes-spend-quota to confirm.")
    if args.max_calls is None or not 1 <= args.max_calls <= HARD_CAP:
        sys.exit(f"smoke_llm: gemini needs --max-calls between 1 and {HARD_CAP}.")
    return smoke_gemini(args.max_calls, os.environ if env is None else env)


if __name__ == "__main__":
    raise SystemExit(main())
