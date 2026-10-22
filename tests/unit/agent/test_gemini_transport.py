"""Gemini transport errors (S13b F5, post-pilot-fixes.md): an httpx transport error becomes a
retryable ProviderError, and no error the adapter raises keeps the request (its header holds the
key) on ``__cause__`` or ``__context__`` (A4). The pilot crash was ``httpx.RemoteProtocolError``
("Server disconnected without sending a response") at dev-38."""

from __future__ import annotations

import traceback
from types import SimpleNamespace as NS

import httpx
import pytest
from google.genai import errors

from dlens.agent.llm.gemini import GeminiProvider
from dlens.agent.llm.types import ProviderError

from .conftest import user

KEY = "S13B-SENTINEL-NOT-A-KEY"  # stands in for the API key; never a real one
URL = f"https://generativelanguage.googleapis.com/v1beta/models/m:generateContent?key={KEY}"


def keyed_request() -> httpx.Request:
    return httpx.Request("POST", URL, headers={"x-goog-api-key": KEY})


def raising(err: BaseException) -> GeminiProvider:
    def generate_content(**_: object) -> object:
        raise err

    return GeminiProvider(
        "gemini-3.5-flash-lite", client=NS(models=NS(generate_content=generate_content))
    )


def raised(err: BaseException) -> ProviderError:
    with pytest.raises(ProviderError) as ei:
        raising(err).send(user("q"), None)
    return ei.value


def assert_holds_no_key(e: ProviderError) -> None:
    assert e.__cause__ is None and e.__context__ is None  # nothing chained, nothing to walk
    for text in (str(e), repr(e), "".join(traceback.format_exception(e))):
        assert KEY not in text


@pytest.mark.parametrize(
    "exc",
    [
        httpx.RemoteProtocolError("Server disconnected without sending a response."),
        httpx.ConnectError("connection refused"),
        httpx.ReadTimeout("timed out"),
        httpx.ConnectTimeout("timed out"),
    ],
)
def test_transport_error_is_a_retryable_provider_error(exc: httpx.TransportError) -> None:
    e = raised(exc)
    assert (e.retryable, e.status_code) == (True, None)
    assert str(e) == f"gemini call failed: {type(exc).__name__}"


def test_transport_error_holds_no_request_or_key() -> None:
    exc = httpx.RemoteProtocolError("Server disconnected", request=keyed_request())
    assert_holds_no_key(raised(exc))


def sdk_error(status: int) -> errors.APIError:
    """The SDK's own error for an HTTP error response to a request carrying the key."""
    body = {"error": {"code": status, "message": "API key not valid.", "status": "X"}}
    resp = httpx.Response(status, json=body, request=keyed_request())
    with pytest.raises(errors.APIError) as ei:
        errors.APIError.raise_for_response(resp)
    assert ei.value.response.request.headers["x-goog-api-key"] == KEY  # the SDK keeps it
    return ei.value


def test_api_error_400_stays_non_retryable_and_holds_no_key() -> None:
    e = raised(sdk_error(400))
    assert (e.retryable, e.status_code) == (False, 400)
    assert str(e) == "gemini call failed (400): API key not valid."
    assert_holds_no_key(e)


def test_api_error_429_stays_retryable_and_holds_no_key() -> None:
    e = raised(sdk_error(429))
    assert (e.retryable, e.status_code) == (True, 429)
    assert_holds_no_key(e)


def test_other_exceptions_are_not_mapped() -> None:
    """Only provider conditions become ProviderError; a crash-class bug still stops the run."""
    with pytest.raises(ValueError):
        raising(ValueError("bug")).send(user("q"), None)
