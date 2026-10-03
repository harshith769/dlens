"""Gemini adapter (google-genai). Our own tool loop: automatic function calling is disabled."""

from __future__ import annotations

import base64
import json
from collections.abc import Mapping, Sequence
from typing import Any

from google.genai import errors
from google.genai import types as gt

from dlens.agent.llm.base import Provider
from dlens.agent.llm.types import LLMResponse, Message, ProviderError, ToolCall, ToolSpec, Usage

SIGNATURE = "thought_signature"
RETRYABLE = (429, 500, 502, 503, 504)


class GeminiConfigError(ValueError):
    pass


class GeminiProvider(Provider):
    name = "gemini"

    def __init__(
        self,
        model: str,
        api_key: str | None = None,
        temperature: float = 1.0,
        thinking_level: str | None = None,
        client: Any = None,
    ):
        if not model or model.endswith("-latest"):
            raise GeminiConfigError(
                "DLENS_GEMINI_MODEL must be a versioned model ID, never empty or '-latest'."
            )
        if (
            thinking_level is not None
            and thinking_level.upper() not in gt.ThinkingLevel.__members__
        ):
            raise GeminiConfigError(
                f"DLENS_GEMINI_THINKING must be one of {sorted(gt.ThinkingLevel.__members__)}."
            )
        self.model = model
        self.temperature = temperature
        self.thinking_level = thinking_level.upper() if thinking_level else None
        if client is None:
            if not api_key:
                raise GeminiConfigError("GEMINI_API_KEY is not set in the environment.")
            from google import genai

            client = genai.Client(api_key=api_key)
        self._client = client

    @classmethod
    def from_env(cls, env: Mapping[str, str]) -> GeminiProvider:
        return cls(
            model=env.get("DLENS_GEMINI_MODEL", ""),
            api_key=env.get("GEMINI_API_KEY"),
            temperature=float(env.get("DLENS_GEMINI_TEMPERATURE") or 1.0),
            thinking_level=env.get("DLENS_GEMINI_THINKING") or None,
        )

    @property
    def params(self) -> dict[str, Any]:
        return {
            "temperature": self.temperature,
            "thinking_level": self.thinking_level,
            "automatic_function_calling": "disabled",
        }

    # -- request ---------------------------------------------------------------------------
    @staticmethod
    def _contents(messages: Sequence[Message]) -> tuple[str | None, list[gt.Content]]:
        system = [m.content for m in messages if m.role == "system"]
        contents: list[gt.Content] = []
        for m in messages:
            if m.role == "system":
                continue
            if m.role == "user":
                contents.append(gt.Content(role="user", parts=[gt.Part(text=m.content)]))
            elif m.role == "assistant":
                parts: list[gt.Part] = []
                if m.content:
                    parts.append(gt.Part(text=m.content))
                for c in m.tool_calls:
                    sig = c.provider_meta.get(SIGNATURE)
                    parts.append(
                        gt.Part(
                            function_call=gt.FunctionCall(name=c.name, args=c.arguments),
                            thought_signature=base64.b64decode(sig) if sig else None,
                        )
                    )
                contents.append(gt.Content(role="model", parts=parts))
            else:  # tool result; consecutive results share one user turn
                part = gt.Part(
                    function_response=gt.FunctionResponse(
                        name=m.name or "", response={"output": m.content}
                    )
                )
                if (
                    contents
                    and contents[-1].role == "user"
                    and contents[-1].parts
                    and (contents[-1].parts[-1].function_response is not None)
                ):
                    contents[-1].parts.append(part)
                else:
                    contents.append(gt.Content(role="user", parts=[part]))
        return ("\n\n".join(system) or None), contents

    def send(
        self,
        messages: Sequence[Message],
        tools: Sequence[ToolSpec] | None,
        response_schema: dict[str, Any] | None = None,
    ) -> LLMResponse:
        system, contents = self._contents(messages)
        config = gt.GenerateContentConfig(
            system_instruction=system,
            temperature=self.temperature,
            # A plain JSON-schema dict goes to response_json_schema; response_schema wants the
            # SDK's Schema type or a Pydantic class.
            response_mime_type="application/json" if response_schema is not None else None,
            response_json_schema=response_schema,
            automatic_function_calling=gt.AutomaticFunctionCallingConfig(disable=True),
            thinking_config=(
                gt.ThinkingConfig(thinking_level=gt.ThinkingLevel(self.thinking_level))
                if self.thinking_level
                else None
            ),
            tools=(
                [
                    gt.Tool(
                        function_declarations=[
                            gt.FunctionDeclaration(
                                name=t.name,
                                description=t.description,
                                parameters_json_schema=t.parameters,
                            )
                            for t in tools
                        ]
                    )
                ]
                if tools
                else None
            ),
        )
        try:
            resp = self._client.models.generate_content(
                model=self.model, contents=contents, config=config
            )
        except errors.APIError as exc:
            raise ProviderError(
                f"gemini call failed ({exc.code}): {exc.message}",
                status_code=exc.code,
                retryable=exc.code in RETRYABLE,
            ) from exc
        return self._parse(resp)

    # -- response --------------------------------------------------------------------------
    @staticmethod
    def _parse(resp: Any) -> LLMResponse:
        texts: list[str] = []
        calls: list[ToolCall] = []
        candidates = getattr(resp, "candidates", None) or []
        parts = (candidates[0].content.parts or []) if candidates and candidates[0].content else []
        for part in parts:
            if part.function_call is not None:
                meta = {}
                if part.thought_signature:
                    meta[SIGNATURE] = base64.b64encode(part.thought_signature).decode()
                fc = part.function_call
                calls.append(
                    ToolCall(
                        id=f"call_{len(calls)}",
                        name=fc.name or "",
                        arguments=json.loads(json.dumps(dict(fc.args or {}))),
                        provider_meta=meta,
                    )
                )
            elif part.text and not part.thought:
                texts.append(part.text)
        usage = getattr(resp, "usage_metadata", None)
        return LLMResponse(
            text="".join(texts).strip(),
            tool_calls=calls,
            usage=Usage(
                input_tokens=getattr(usage, "prompt_token_count", 0) or 0,
                output_tokens=getattr(usage, "candidates_token_count", 0) or 0,
            ),
        )
