"""Seed (S13c S, s13c-design.md): Ollama sends seed 42 with every call, for S1 and S4 alike (both
build their client with make_client); the seed is part of the provider params, so the cache key
moves; the manifest records the seed actually sent. Gemini: the seed field exists behind
DLENS_GEMINI_SEED and is OFF by default (no field sent, cache keys unchanged)."""

from __future__ import annotations

from types import SimpleNamespace as NS
from typing import Any

from google.genai import types as gt

from dlens.agent.llm.cache import cache_key
from dlens.agent.llm.gemini import GeminiProvider
from dlens.agent.llm.ollama import SEED, OllamaProvider

from .conftest import user


def test_ollama_sends_seed_42() -> None:
    sent: dict[str, Any] = {}

    def chat(**kw: Any) -> Any:
        sent.update(kw)
        return NS(message=NS(content="ok", tool_calls=None), prompt_eval_count=1, eval_count=1)

    OllamaProvider(client=NS(chat=chat)).send(user("hi"), None)
    assert SEED == 42 and sent["options"]["seed"] == 42


def test_ollama_seed_moves_the_cache_key() -> None:
    p = OllamaProvider(client=object())
    msgs = user("hi")
    with_seed = cache_key(p.name, p.model, msgs, None, p.params)
    without = cache_key(
        p.name, p.model, msgs, None, {k: v for k, v in p.params.items() if k != "seed"}
    )
    assert p.params["seed"] == 42 and with_seed != without


def test_s1_and_s4_get_the_same_ollama_params(monkeypatch: Any, tmp_path: Any) -> None:
    """Both runners build their client with make_client, so one provider rule covers both."""
    from dlens.agent.llm import make_client

    monkeypatch.setenv("DLENS_PROVIDER", "ollama")
    monkeypatch.setenv("DLENS_CACHE_DIR", str(tmp_path / "c"))
    monkeypatch.setenv("DLENS_STATE_DIR", str(tmp_path / "s"))
    assert make_client().provider.params["seed"] == 42


def _gemini_config(env: dict[str, str]) -> tuple[GeminiProvider, Any]:
    seen: dict[str, Any] = {}

    def generate_content(**kw: Any) -> Any:
        seen.update(kw)
        return NS(candidates=[NS(content=NS(parts=[gt.Part(text="ok")]))],
                  usage_metadata=NS(prompt_token_count=1, candidates_token_count=1))  # fmt: skip

    prov = GeminiProvider.from_env({"DLENS_GEMINI_MODEL": "gemini-3.5-flash-lite", **env})
    prov._client = NS(models=NS(generate_content=generate_content))
    prov.send(user("q"), None)
    return prov, seen["config"]


def test_gemini_seed_is_off_by_default() -> None:
    prov, cfg = _gemini_config({"GEMINI_API_KEY": "x"})
    assert cfg.seed is None and "seed" not in prov.params  # no field sent, cache keys unchanged


def test_gemini_seed_when_set() -> None:
    prov, cfg = _gemini_config({"GEMINI_API_KEY": "x", "DLENS_GEMINI_SEED": "42"})
    assert cfg.seed == 42 and prov.params["seed"] == 42


def test_manifest_records_the_seed_sent() -> None:
    import sys
    from pathlib import Path

    sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "eval"))
    from systems.manifest import model_identity

    off = model_identity(GeminiProvider("gemini-3.5-flash-lite", client=object()))
    on = model_identity(GeminiProvider("gemini-3.5-flash-lite", client=object(), seed=42))
    assert off["sampling"]["seed"] is None and off["request"]["seed"] is None
    assert on["sampling"]["seed"] == 42 and on["request"]["seed"] == 42
