"""One-call Gemini seed smoke (S13c S; the OWNER runs it, it spends 1 call of free quota).

Sends one short prompt to gemini-3.5-flash-lite with ``seed: 42`` through ``LLMClient`` (quota
counted on the dev counter; a throwaway cache, so the call is real) and prints only the outcome:
``OK (HTTP 200)``, or ``ProviderError (HTTP <status>)``, or the exception class name. It never
prints the response text, the key or the request. If it succeeds, turning the Gemini seed on by
default is one commit with a test; if it fails, the seed stays off and that is recorded.

    DLENS_PROVIDER=gemini DLENS_GEMINI_MODEL=gemini-3.5-flash-lite DLENS_GEMINI_SEED=42 \\
      GEMINI_DAILY_BUDGET=475 uv run --extra agent python scripts/smoke_gemini_seed.py --allow-cloud
"""

from __future__ import annotations

import argparse
import os
import sys
import tempfile

MODEL = "gemini-3.5-flash-lite"
SEED = "42"
BUDGET = "475"


def check_env(env: dict[str, str]) -> str | None:
    """The reason to refuse, or None. The command pins provider, model, seed and budget."""
    want = {
        "DLENS_PROVIDER": "gemini",
        "DLENS_GEMINI_MODEL": MODEL,
        "DLENS_GEMINI_SEED": SEED,
        "GEMINI_DAILY_BUDGET": BUDGET,
    }
    for k, v in want.items():
        if env.get(k) != v:
            return f"{k} must be {v!r} (see the command in the docstring)"
    return None


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawTextHelpFormatter)
    ap.add_argument("--allow-cloud", action="store_true", help="required: spends 1 Gemini call")
    ns = ap.parse_args(argv)
    if not ns.allow_cloud:
        print("refused: pass --allow-cloud (this spends 1 Gemini call of free quota)")
        return 2
    reason = check_env(dict(os.environ))
    if reason:
        print(f"refused: {reason}")
        return 2
    from dlens.agent.llm import Message, make_client
    from dlens.agent.llm.types import ProviderError

    with tempfile.TemporaryDirectory() as cache:
        os.environ["DLENS_CACHE_DIR"] = cache  # a real call, never a cache hit
        client = make_client()
        try:
            client.chat([Message(role="user", content="Reply with the single word: ok")])
        except ProviderError as e:
            print(f"ProviderError (HTTP {e.status_code})")
            return 1
        except Exception as e:  # noqa: BLE001 - only the class name is printed
            print(type(e).__name__)
            return 1
    print("OK (HTTP 200)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
