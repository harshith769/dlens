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
