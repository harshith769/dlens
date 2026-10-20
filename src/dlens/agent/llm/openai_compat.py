"""OpenAI-compatible adapter (ADR 0012): one HTTP shape for Groq, OpenRouter, LM Studio, vLLM,
OpenAI and Ollama's own ``/v1`` endpoint. Groq is a preset of it, not its own SDK.

Settings come from the environment. The API key is never stored on the provider: only the *name*
of its environment variable is, and the value is read at send time for the ``Authorization``
header. It never enters ``params`` (the cache key), the cache, records or exception text, and
errors are raised ``from None`` so no chained httpx request (which holds the headers) is kept.
"""

from __future__ import annotations

import json
import os
from collections.abc import Mapping, Sequence
from typing import Any
from urllib.parse import urlparse

import httpx

from dlens.agent.llm.base import Provider
from dlens.agent.llm.ollama import strip_think
from dlens.agent.llm.types import LLMResponse, Message, ProviderError, ToolCall, ToolSpec, Usage

GROQ_BASE_URL = "https://api.groq.com/openai/v1"
JSON_MODES = ("json_schema", "json_object", "off")
LOCAL_HOSTS = {"localhost", "127.0.0.1", "::1"}
RETRYABLE = (429, 500, 502, 503, 504)
ERROR_BODY_CHARS = 300
TIMEOUT_S = 120.0


class OpenAICompatConfigError(ValueError):
    pass


def is_local(base_url: str) -> bool:
    return urlparse(base_url).hostname in LOCAL_HOSTS


class OpenAICompatProvider(Provider):
    def __init__(
        self,
        name: str,
        base_url: str,
        model: str,
        key_env: str | None = None,
        *,
        temperature: float = 0.0,
        json_mode: str = "json_schema",
        env: Mapping[str, str] | None = None,
        client: httpx.Client | None = None,
    ):
        if not base_url or urlparse(base_url).scheme not in ("http", "https"):
            raise OpenAICompatConfigError(f"{name}: base URL must be an http(s) URL.")
        if not model or model.endswith("-latest"):
            raise OpenAICompatConfigError(
                f"{name}: the model must be a versioned model ID, never empty or '-latest'."
            )
        if json_mode not in JSON_MODES:
            raise OpenAICompatConfigError(f"{name}: JSON mode must be one of {list(JSON_MODES)}.")
        self.name = name
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.key_env = key_env or None
        self.temperature = temperature
        self.json_mode = json_mode
        self.local = is_local(self.base_url)
        self._env = os.environ if env is None else env
        if not self.local and not (self.key_env and self._env.get(self.key_env)):
            raise OpenAICompatConfigError(
                f"{name}: a non-local endpoint needs an API key; set the variable named by "
                f"the key-env setting ({self.key_env or 'unset'})."
            )
        self._client = client or httpx.Client(timeout=TIMEOUT_S)

    @classmethod
    def from_env(cls, env: Mapping[str, str], preset: str = "openai") -> OpenAICompatProvider:
        if preset == "groq":
            return cls(
                "groq",
                GROQ_BASE_URL,
                env.get("DLENS_GROQ_MODEL", ""),
                "GROQ_API_KEY",
                temperature=float(env.get("DLENS_GROQ_TEMPERATURE") or 0.0),
                json_mode=env.get("DLENS_GROQ_JSON_MODE") or "json_schema",
                env=env,
            )
        return cls(
            "openai",
            env.get("DLENS_OPENAI_BASE_URL", ""),
            env.get("DLENS_OPENAI_MODEL", ""),
            env.get("DLENS_OPENAI_KEY_ENV") or None,
            temperature=float(env.get("DLENS_OPENAI_TEMPERATURE") or 0.0),
            json_mode=env.get("DLENS_OPENAI_JSON_MODE") or "json_schema",
            env=env,
        )

    @property
    def params(self) -> dict[str, Any]:
        # The base URL is part of the cache key: the same model id on two endpoints is two models.
        return {
            "base_url": self.base_url,
            "temperature": self.temperature,
            "json_mode": self.json_mode,
        }

    # -- request ---------------------------------------------------------------------------
    @staticmethod
    def _convert(m: Message) -> dict[str, Any]:
        if m.role == "tool":
            return {"role": "tool", "tool_call_id": m.tool_call_id or "", "content": m.content}
        out: dict[str, Any] = {"role": m.role, "content": m.content}
        if m.role == "assistant" and m.tool_calls:
            out["content"] = m.content or None
            out["tool_calls"] = [
                {
                    "id": c.id,
                    "type": "function",
                    "function": {"name": c.name, "arguments": json.dumps(c.arguments)},
                }
                for c in m.tool_calls
            ]
        return out

    def body(
        self,
        messages: Sequence[Message],
        tools: Sequence[ToolSpec] | None,
        response_schema: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        out: dict[str, Any] = {
            "model": self.model,
            "messages": [self._convert(m) for m in messages],
            "temperature": self.temperature,
        }
        if tools:
            out["tools"] = [
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
        if response_schema is not None and self.json_mode == "json_schema":
            out["response_format"] = {
                "type": "json_schema",
                "json_schema": {"name": "answer", "schema": response_schema},
            }
        elif response_schema is not None and self.json_mode == "json_object":
            out["response_format"] = {"type": "json_object"}
        return out

    def _headers(self) -> dict[str, str]:
        headers = {"Content-Type": "application/json"}
        key = self._env.get(self.key_env) if self.key_env else None
        if key:
            headers["Authorization"] = f"Bearer {key}"
        return headers

    def send(
        self,
        messages: Sequence[Message],
        tools: Sequence[ToolSpec] | None,
        response_schema: dict[str, Any] | None = None,
    ) -> LLMResponse:
        url = f"{self.base_url}/chat/completions"
        try:
            resp = self._client.post(
                url, json=self.body(messages, tools, response_schema), headers=self._headers()
            )
        except httpx.HTTPError as exc:
            # from None: the chained exception holds the request, and the request holds the key.
            raise ProviderError(
                f"{self.name} call failed: {type(exc).__name__}", retryable=True
            ) from None
        if resp.status_code >= 400:
            body = " ".join(resp.text.split())[:ERROR_BODY_CHARS]
            raise ProviderError(
                f"{self.name} call failed ({resp.status_code}): {body}",
                status_code=resp.status_code,
                retryable=resp.status_code in RETRYABLE,
            ) from None
        try:
            data = resp.json()
            msg = data["choices"][0]["message"]
        except (ValueError, KeyError, IndexError, TypeError):
            raise ProviderError(f"{self.name} returned an unreadable response") from None
        return self._parse(msg, data.get("usage") or {})

    # -- response --------------------------------------------------------------------------
    def _parse(self, msg: Mapping[str, Any], usage: Mapping[str, Any]) -> LLMResponse:
        calls: list[ToolCall] = []
        for i, c in enumerate(msg.get("tool_calls") or []):
            fn = c.get("function") or {}
            raw = fn.get("arguments") or "{}"
            try:
                args = json.loads(raw) if isinstance(raw, str) else dict(raw)
            except ValueError:
                raise ProviderError(
                    f"{self.name}: malformed tool call arguments for {fn.get('name')!r}"
                ) from None
            if not isinstance(args, dict):
                raise ProviderError(f"{self.name}: tool call arguments are not an object")
            # Ids are positional, never the server's random ones, so replayed histories hash to
            # the same cache key.
            calls.append(ToolCall(id=f"call_{i}", name=fn.get("name") or "", arguments=args))
        return LLMResponse(
            text=strip_think(msg.get("content") or ""),
            tool_calls=calls,
            usage=Usage(
                input_tokens=int(usage.get("prompt_tokens") or 0),
                output_tokens=int(usage.get("completion_tokens") or 0),
            ),
        )
