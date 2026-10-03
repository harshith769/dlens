"""Provider-neutral message and response types. Everything here round-trips through JSON."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field

Role = Literal["system", "user", "assistant", "tool"]


class ToolSpec(BaseModel):
    name: str
    description: str
    parameters: dict[str, Any] = Field(default_factory=lambda: {"type": "object", "properties": {}})


class ToolCall(BaseModel):
    id: str
    name: str
    arguments: dict[str, Any] = Field(default_factory=dict)
    # Opaque, provider-specific strings that must be replayed with the history
    # (e.g. Gemini 3 `thought_signature`, base64-encoded).
    provider_meta: dict[str, str] = Field(default_factory=dict)


class Message(BaseModel):
    role: Role
    content: str = ""
    tool_calls: list[ToolCall] = Field(default_factory=list)  # assistant messages
    tool_call_id: str | None = None  # tool messages: which call this answers
    name: str | None = None  # tool messages: the tool's name


class Usage(BaseModel):
    input_tokens: int = 0
    output_tokens: int = 0


class LLMResponse(BaseModel):
    text: str = ""
    tool_calls: list[ToolCall] = Field(default_factory=list)
    usage: Usage = Field(default_factory=Usage)
    cached: bool = False

    def as_message(self) -> Message:
        """The assistant message to append to the history (keeps provider_meta)."""
        return Message(role="assistant", content=self.text, tool_calls=self.tool_calls)


class QuotaExceeded(RuntimeError):
    """Raised before sending when the provider's daily budget is used up."""


class InputTooLarge(ValueError):
    """Raised before sending when the estimated input exceeds the token cap."""


class ProviderError(RuntimeError):
    """A provider call failed. LLMClient never retries; the caller decides."""

    def __init__(self, message: str, *, status_code: int | None = None, retryable: bool = False):
        super().__init__(message)
        self.status_code = status_code
        self.retryable = retryable
