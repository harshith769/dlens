"""S13c A1 (s13c-design.md): no error the OpenAI-compatible adapter raises keeps the httpx
request (whose Authorization header holds the key) on ``__cause__`` or ``__context__``, and no
text form of it contains the key. Same check as the Gemini adapter's (S13b F5)."""

from __future__ import annotations

import traceback
from typing import Any

import httpx
import pytest

from dlens.agent.llm.openai_compat import OpenAICompatProvider
from dlens.agent.llm.types import ProviderError

from .conftest import user

KEY = "sk-S13C-SENTINEL-not-a-key"
REMOTE = "https://api.example.test/v1"


def raising(exc: Exception) -> OpenAICompatProvider:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.headers["authorization"] == f"Bearer {KEY}"
        raise exc

    return OpenAICompatProvider(
        "openai",
        REMOTE,
        "some-model",
        "MY_KEY",
        env={"MY_KEY": KEY},
        client=httpx.Client(transport=httpx.MockTransport(handler)),
    )


def assert_holds_no_key(e: ProviderError) -> None:
    assert e.__cause__ is None and e.__context__ is None
    for text in (str(e), repr(e), "".join(traceback.format_exception(e))):
        assert KEY not in text


@pytest.mark.parametrize(
    "exc",
    [
        httpx.ConnectError("refused"),
        httpx.RemoteProtocolError("Server disconnected"),
        httpx.ReadTimeout("timed out"),
    ],
)
def test_transport_error_holds_no_request(exc: Exception) -> None:
    with pytest.raises(ProviderError) as ei:
        raising(exc).send(user("q"), None)
    e = ei.value
    assert e.retryable and e.status_code is None
    assert str(e) == f"openai call failed: {type(exc).__name__}"
    assert_holds_no_key(e)


def test_http_error_status_path_holds_no_request() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(401, text="bad key")

    prov: Any = raising(httpx.ConnectError("unused"))
    prov._client = httpx.Client(transport=httpx.MockTransport(handler))
    with pytest.raises(ProviderError) as ei:
        prov.send(user("q"), None)
    assert ei.value.status_code == 401 and not ei.value.retryable
    assert_holds_no_key(ei.value)
