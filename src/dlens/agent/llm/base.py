"""LLMClient: the only door to a model. Order of checks matters:

1. token cap      -> InputTooLarge   (nothing consumed)
2. cache lookup   -> hit returns, no limiter, no quota, no network
3. quota reserve  -> QuotaExceeded   (before sending, never after)
4. rate limiter   -> may sleep
5. provider send  -> ProviderError propagates; no retries here
6. cache store
"""

from __future__ import annotations

import os
from abc import ABC, abstractmethod
from collections.abc import Mapping, Sequence
from typing import Any

from dlens.agent.llm.cache import ResponseCache, cache_key
from dlens.agent.llm.config import cache_path, quota_path
from dlens.agent.llm.quota import BUDGET_ENV, QuotaCounter, default_budgets
from dlens.agent.llm.ratelimit import RPM_LIMITS, RateLimiter
from dlens.agent.llm.tokens import MAX_INPUT_TOKENS, estimate_tokens
from dlens.agent.llm.types import InputTooLarge, LLMResponse, Message, ToolSpec


class Provider(ABC):
    name: str
    model: str

    @property
    @abstractmethod
    def params(self) -> dict[str, Any]:
        """Everything besides messages/tools that changes the output; part of the cache key."""

    @abstractmethod
    def send(
        self,
        messages: Sequence[Message],
        tools: Sequence[ToolSpec] | None,
        response_schema: dict[str, Any] | None = None,
    ) -> LLMResponse:
        """``response_schema`` (a JSON schema) asks for structured JSON output in ``text``."""


class LLMClient:
    def __init__(
        self,
        provider: Provider,
        cache: ResponseCache,
        quota: QuotaCounter,
        limiter: RateLimiter,
        max_input_tokens: int = MAX_INPUT_TOKENS,
    ):
        self.provider = provider
        self.cache = cache
        self.quota = quota
        self.limiter = limiter
        self.max_input_tokens = max_input_tokens

    def chat(
        self,
        messages: Sequence[Message],
        tools: Sequence[ToolSpec] | None = None,
        response_schema: dict[str, Any] | None = None,
    ) -> LLMResponse:
        estimated = estimate_tokens(messages, tools, response_schema)
        if estimated > self.max_input_tokens:
            raise InputTooLarge(f"~{estimated} input tokens exceeds cap of {self.max_input_tokens}")
        key = cache_key(
            self.provider.name,
            self.provider.model,
            messages,
            tools,
            self.provider.params,
            response_schema,
        )
        hit = self.cache.get(key)
        if hit is not None:
            return hit.model_copy(update={"cached": True})
        self.quota.reserve(self.provider.name)
        self.limiter.acquire()
        response = self.provider.send(messages, tools, response_schema)
        response = response.model_copy(update={"cached": False})
        self.cache.put(key, response)
        return response


def make_client(provider: str | None = None, env: Mapping[str, str] | None = None) -> LLMClient:
    """Build a client from the environment. DLENS_PROVIDER picks the provider (default ollama)."""
    env = os.environ if env is None else env
    name = (provider or env.get("DLENS_PROVIDER") or "ollama").lower()
    if name == "ollama":
        from dlens.agent.llm.ollama import OllamaProvider

        prov: Provider = OllamaProvider.from_env(env)
    elif name == "gemini":
        from dlens.agent.llm.gemini import GeminiProvider

        prov = GeminiProvider.from_env(env)
    elif name in ("openai", "groq"):
        from dlens.agent.llm.openai_compat import OpenAICompatConfigError, OpenAICompatProvider

        compat = OpenAICompatProvider.from_env(env, preset=name)
        if not compat.local and default_budgets(env).get(name) is None:
            raise OpenAICompatConfigError(
                f"{name}: a non-local endpoint needs a daily call budget "
                f"({BUDGET_ENV[name]}); a cloud call is never unmetered."
            )
        prov = compat
    else:
        raise ValueError(
            f"Unknown DLENS_PROVIDER {name!r}; expected ollama, gemini, openai or groq."
        )
    rpm = RPM_LIMITS[name]
    if name == "openai" and env.get("DLENS_OPENAI_RPM"):
        rpm = int(env["DLENS_OPENAI_RPM"])
    return LLMClient(
        prov,
        ResponseCache(cache_path(env)),
        QuotaCounter(quota_path(env), default_budgets(env)),
        RateLimiter(rpm),
    )
