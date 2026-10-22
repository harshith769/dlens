"""eval/systems/manifest.py, S13 additions shared by S1 and S4: ``model_identity`` (moved from
s4.py; Ollama digest and version, Gemini's request settings) and ``quota_info`` (the daily cap a
run ran under). No network."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

pytest.importorskip("httpx")

from dlens.agent.llm.base import LLMClient  # noqa: E402
from dlens.agent.llm.cache import ResponseCache  # noqa: E402
from dlens.agent.llm.quota import QuotaCounter, default_budgets  # noqa: E402
from dlens.agent.llm.ratelimit import RateLimiter  # noqa: E402
from systems.manifest import ROOT, model_identity, quota_info  # noqa: E402


class _FakeOllamaClient:
    class _M:
        def __init__(self, model: str, digest: str) -> None:
            self.model, self.digest = model, digest

    def list(self) -> Any:
        return type("L", (), {"models": [self._M("qwen3:4b-x", "sha256:abc123")]})()

    def show(self, model: str) -> Any:
        return type("S", (), {"parameters": 'stop "<|im_end|>"'})()


class _Named:
    def __init__(self, name: str, model: str = "m-1") -> None:
        self.name, self.model = name, model

    @property
    def params(self) -> dict[str, Any]:
        return {"temperature": 0}


def test_model_identity_records_digest_version_and_sampling(monkeypatch: Any) -> None:
    """S12b STOP 2: the manifest pins the Ollama model by digest, the server version, the
    Modelfile defaults and the sampling settings sent (temperature 0, num_ctx; seed 42 since
    S13c)."""
    import httpx

    from dlens.agent.llm.ollama import NUM_CTX, OllamaProvider

    resp = type("R", (), {"json": lambda self: {"version": "0.35.1"}})()
    monkeypatch.setattr(httpx, "get", lambda url, timeout: resp)
    prov = OllamaProvider("qwen3:4b-x", client=_FakeOllamaClient())
    ident = model_identity(prov)
    assert ident["digest"] == "sha256:abc123" and ident["ollama_version"] == "0.35.1"
    assert ident["sampling"] == {"temperature": 0, "num_ctx": NUM_CTX, "think": False, "seed": 42}
    assert ident["modelfile_parameters"] == 'stop "<|im_end|>"'
    with pytest.raises(SystemExit):
        model_identity(OllamaProvider("not-pulled", client=_FakeOllamaClient()))


def test_other_identity_has_no_digest() -> None:
    ident = model_identity(_Named("fake"))
    assert "digest" not in ident and "request" not in ident and ident["sampling"]["seed"] is None


def test_gemini_identity_records_the_thinking_config_as_sent() -> None:
    """pilot-design §2: temperature 1.0 and the thinking setting exactly as the request carries
    it; unset means no thinkingConfig field at all (the model's default level)."""
    pytest.importorskip("google.genai")
    from dlens.agent.llm.gemini import GeminiProvider

    unset = model_identity(GeminiProvider("gemini-3.5-flash-lite", client=object()))
    assert unset["request"]["temperature"] == 1.0
    assert unset["request"]["thinking_config"] is None
    assert "not sent" in unset["request"]["thinking_config_note"]
    low = GeminiProvider("gemini-3.5-flash-lite", thinking_level="low", client=object())
    assert model_identity(low)["request"]["thinking_config"] == {"thinking_level": "LOW"}


def _client(tmp: Path, name: str, budgets: dict[str, int | None]) -> LLMClient:
    return LLMClient(
        _Named(name),  # type: ignore[arg-type]
        ResponseCache(tmp / "cache.sqlite"),
        QuotaCounter(tmp / "state" / "quota.sqlite", budgets),
        RateLimiter(None),
    )


def test_quota_info_records_the_effective_cap_and_shared_counter(tmp_path: Path) -> None:
    budgets = default_budgets({"GEMINI_DAILY_BUDGET": "380"})
    client = _client(tmp_path, "gemini", budgets)
    for _ in range(3):
        client.quota.reserve("gemini")
    # a second counter on the same file (another process, e.g. S4 after S1) sees the same count
    other = QuotaCounter(tmp_path / "state" / "quota.sqlite", budgets)
    other.reserve("gemini")
    info = quota_info(client)
    assert info["provider"] == "gemini" and info["daily_budget"] == 380
    assert info["used_today"] == 4
    assert "America/Los_Angeles" in info["day_basis"] and len(info["day_key"]) == 10
    assert info["store"] == "user state dir (outside the repo)"  # tmp_path: never a local path
    assert str(tmp_path) not in str(info) and str(Path.home()) not in str(info)


def test_quota_info_ollama_has_no_cap_and_repo_store_is_relative(tmp_path: Path) -> None:
    client = _client(tmp_path, "ollama", {"ollama": None})
    assert quota_info(client)["daily_budget"] is None

    class _Stub:  # a counter whose file is inside the repo (never opened)
        path = ROOT / "eval" / "cache" / "state" / "quota.sqlite"
        budgets: dict[str, int | None] = {"ollama": None}

        def used(self, provider: str) -> int:
            return 0

    client.quota = _Stub()  # type: ignore[assignment]
    assert quota_info(client)["store"] == "eval/cache/state"
