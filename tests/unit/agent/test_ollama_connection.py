"""S13c A2 (s13c-design.md): a lost or refused Ollama connection is a retryable ProviderError,
as in the Gemini and OpenAI-compatible adapters; a server error keeps its status mapping; nothing
is chained."""

from __future__ import annotations

from types import SimpleNamespace as NS

import httpx
import pytest

from dlens.agent.llm.ollama import OllamaProvider
from dlens.agent.llm.types import ProviderError

from .conftest import user


def raising(exc: BaseException) -> OllamaProvider:
    def chat(**_: object) -> object:
        raise exc

    return OllamaProvider(client=NS(chat=chat))


def raised(exc: BaseException) -> ProviderError:
    with pytest.raises(ProviderError) as ei:
        raising(exc).send(user("hi"), None)
    return ei.value


@pytest.mark.parametrize(
    "exc",
    [
        ConnectionError("Failed to connect to Ollama."),  # what the client raises on ConnectError
        httpx.RemoteProtocolError("Server disconnected without sending a response."),
        httpx.ReadTimeout("timed out"),
    ],
)
def test_connection_errors_are_retryable(exc: BaseException) -> None:
    e = raised(exc)
    assert (e.retryable, e.status_code) == (True, None)
    assert str(e) == f"ollama call failed: {type(exc).__name__}"
    assert e.__cause__ is None and e.__context__ is None


def test_server_error_keeps_its_status_mapping() -> None:
    e = raised(type("ResponseError", (Exception,), {"status_code": 404})("model not found"))
    assert (e.retryable, e.status_code) == (False, 404)
    assert e.__cause__ is None and e.__context__ is None


def test_other_exception_without_status_is_not_retryable() -> None:
    e = raised(ValueError("bad"))
    assert (e.retryable, e.status_code) == (False, None)
