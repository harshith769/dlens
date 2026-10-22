"""The owner's one-call Gemini seed smoke refuses before any call unless --allow-cloud and the
pinned env are given (S13c S). No network: the refusals happen before a client is built."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))

import smoke_gemini_seed as S  # noqa: E402

PINNED = {
    "DLENS_PROVIDER": "gemini",
    "DLENS_GEMINI_MODEL": "gemini-3.5-flash-lite",
    "DLENS_GEMINI_SEED": "42",
    "GEMINI_DAILY_BUDGET": "475",
}


def test_refuses_without_allow_cloud(capsys: pytest.CaptureFixture[str]) -> None:
    assert S.main([]) == 2
    assert "refused" in capsys.readouterr().out


@pytest.mark.parametrize("key", sorted(PINNED))
def test_refuses_unless_every_setting_is_pinned(key: str, monkeypatch: pytest.MonkeyPatch) -> None:
    for k, v in PINNED.items():
        monkeypatch.setenv(k, v)
    monkeypatch.setenv(key, "something-else")
    assert S.main(["--allow-cloud"]) == 2


def test_pinned_env_passes_the_check() -> None:
    assert S.check_env(dict(PINNED)) is None
