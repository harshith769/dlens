import os

import pytest

from dlens.agent.llm.ollama import OllamaProvider

from .conftest import user

pytestmark = [
    pytest.mark.ollama,
    pytest.mark.skipif(
        os.environ.get("DLENS_RUN_OLLAMA") != "1" or os.environ.get("CI") == "true",
        reason="live Ollama test: set DLENS_RUN_OLLAMA=1 locally",
    ),
]


def test_live_ollama_answers_without_think_tags():
    resp = OllamaProvider().send(user("Reply with the single word: ok"), None)
    assert resp.text
    assert "<think>" not in resp.text
    assert resp.usage.input_tokens > 0


def test_live_ollama_openai_compatible_endpoint_is_cached(tmp_path):
    """One short call to Ollama's local OpenAI-compatible endpoint, then the same call from the
    cache (S11 step 2 smoke)."""
    from dlens.agent.llm import make_client

    env = {
        "DLENS_CACHE_DIR": str(tmp_path / "c"),
        "DLENS_STATE_DIR": str(tmp_path / "s"),
        "DLENS_OPENAI_BASE_URL": "http://localhost:11434/v1",
        "DLENS_OPENAI_MODEL": "qwen3:4b-instruct-2507-q4_K_M",
    }
    client = make_client("openai", env)
    schema = {
        "type": "object",
        "properties": {"answer": {"type": "string"}},
        "required": ["answer"],
    }
    first = client.chat(user('Reply with JSON {"answer": "ok"}'), None, schema)
    second = client.chat(user('Reply with JSON {"answer": "ok"}'), None, schema)
    assert first.text and "<think>" not in first.text
    assert (first.cached, second.cached) == (False, True) and second.text == first.text
