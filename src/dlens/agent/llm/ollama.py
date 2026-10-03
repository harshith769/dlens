"""Ollama adapter: qwen3:4b, temperature 0, thinking off, num_ctx 8192."""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from typing import Any

from dlens.agent.llm.base import Provider
from dlens.agent.llm.types import LLMResponse, Message, ProviderError, ToolCall, ToolSpec, Usage

DEFAULT_MODEL = "qwen3:4b"
NUM_CTX = 8192

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
        return {"temperature": 0, "num_ctx": NUM_CTX, "think": False}

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

    def send(self, messages: Sequence[Message], tools: Sequence[ToolSpec] | None) -> LLMResponse:
        kwargs: dict[str, Any] = {
            "model": self.model,
            "messages": [self._convert(m) for m in messages],
            "options": {"temperature": 0, "num_ctx": NUM_CTX},
            "think": False,
        }
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
        try:
            resp = self._client.chat(**kwargs)
        except Exception as exc:  # ollama.ResponseError, httpx/connection errors
            status = getattr(exc, "status_code", None)
            raise ProviderError(
                f"ollama call failed: {exc}",
                status_code=status,
                retryable=status in (429, 500, 502, 503, 504),
            ) from exc
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
