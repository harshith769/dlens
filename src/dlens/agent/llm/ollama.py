"""Ollama adapter: Qwen3-4B-Instruct-2507 (non-thinking), temperature 0, num_ctx 8192, seed 42."""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from typing import Any

import httpx

from dlens.agent.llm.base import Provider
from dlens.agent.llm.types import LLMResponse, Message, ProviderError, ToolCall, ToolSpec, Usage

DEFAULT_MODEL = "qwen3:4b-instruct-2507-q4_K_M"
NUM_CTX = 8192
# S13c S (owner, 22 Oct 2026): temperature 0 alone was not deterministic on the local server (4 of
# 12 identical prompts gave 2 outputs over 5 sends); seed 42 gave 1 in all 12. S1 and S4 alike.
SEED = 42

_THINK_BLOCK = re.compile(r"<think>.*?</think>", re.DOTALL)
_THINK_OPEN = re.compile(r"<think>.*\Z", re.DOTALL)  # unterminated: model ran out of tokens


def strip_think(text: str) -> str:
    text = _THINK_BLOCK.sub("", text)
    text = _THINK_OPEN.sub("", text)
    if "</think>" in text:  # opening tag was swallowed
        text = text.rsplit("</think>", 1)[1]
    return text.strip()


class OllamaProvider(Provider):
    name = "ollama"

    def __init__(self, model: str = DEFAULT_MODEL, client: Any = None):
        self.model = model
        if client is None:
            import ollama

            client = ollama.Client()
        self._client = client

    @classmethod
    def from_env(cls, env: Mapping[str, str]) -> OllamaProvider:
        return cls(env.get("OLLAMA_MODEL") or DEFAULT_MODEL)

    @property
    def params(self) -> dict[str, Any]:
        return {"temperature": 0, "num_ctx": NUM_CTX, "think": False, "seed": SEED}

    @staticmethod
    def _convert(m: Message) -> dict[str, Any]:
        out: dict[str, Any] = {"role": m.role, "content": m.content}
        if m.tool_calls:
            out["tool_calls"] = [
                {"function": {"name": c.name, "arguments": c.arguments}} for c in m.tool_calls
            ]
        if m.role == "tool" and m.name:
            out["tool_name"] = m.name
        return out

    def send(
        self,
        messages: Sequence[Message],
        tools: Sequence[ToolSpec] | None,
        response_schema: dict[str, Any] | None = None,
    ) -> LLMResponse:
        kwargs: dict[str, Any] = {
            "model": self.model,
            "messages": [self._convert(m) for m in messages],
            "options": {"temperature": 0, "num_ctx": NUM_CTX, "seed": SEED},
            "think": False,
        }
        if response_schema is not None:
            kwargs["format"] = response_schema
        if tools:
            kwargs["tools"] = [
                {
                    "type": "function",
                    "function": {
                        "name": t.name,
                        "description": t.description,
                        "parameters": t.parameters,
                    },
                }
                for t in tools
            ]
        # S13c A2: a lost or refused connection (the client turns httpx.ConnectError into
        # ConnectionError; timeouts and dropped connections stay httpx errors) is retryable, as
        # in gemini.py and openai_compat.py: the loop retries once, at no quota cost. Raised after
        # the except block, so nothing is chained.
        err: ProviderError | None = None
        try:
            resp = self._client.chat(**kwargs)
        except (ConnectionError, httpx.TransportError) as exc:
            err = ProviderError(f"ollama call failed: {type(exc).__name__}", retryable=True)
        except Exception as exc:  # ollama.ResponseError: the server answered with an error
            status = getattr(exc, "status_code", None)
            err = ProviderError(
                f"ollama call failed: {exc}",
                status_code=status,
                retryable=status in (429, 500, 502, 503, 504),
            )
        if err is not None:
            raise err from None
        msg = resp.message
        # Ids are positional, never random, so replayed histories hash to the same cache key.
        calls = [
            ToolCall(id=f"call_{i}", name=c.function.name, arguments=dict(c.function.arguments))
            for i, c in enumerate(msg.tool_calls or [])
        ]
        return LLMResponse(
            text=strip_think(msg.content or ""),
            tool_calls=calls,
            usage=Usage(
                input_tokens=resp.prompt_eval_count or 0, output_tokens=resp.eval_count or 0
            ),
        )
