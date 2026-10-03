"""One live local LLM call through LLMClient (cache, quota and rate limit included).

Usage:  uv run python scripts/smoke_llm.py --provider ollama

Runs the same prompt twice: the second call must be a cache hit. Cache and quota files go to a
throwaway temp dir, so this never touches the real quota counter. Gemini is refused on purpose
(no live Gemini calls until the owner allows it).
"""

import argparse
import sys
import tempfile

from dlens.agent.llm import Message, make_client


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--provider", required=True)
    args = ap.parse_args()
    if args.provider != "ollama":
        sys.exit("smoke_llm.py only supports --provider ollama (no live cloud calls from here).")
    with tempfile.TemporaryDirectory() as tmp:
        client = make_client("ollama", {"DLENS_CACHE_DIR": tmp, "DLENS_STATE_DIR": tmp})
        msgs = [Message(role="user", content="Reply with the single word: ok")]
        for attempt in (1, 2):
            r = client.chat(msgs)
            print(f"call {attempt}: cached={r.cached} usage={r.usage.model_dump()} text={r.text!r}")
            assert ("<think>" not in r.text) and (r.cached == (attempt == 2))
    print("OK: live call worked and the repeat was served from cache.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
