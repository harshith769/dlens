"""Where the cache and the quota counter live. Separate files, so clearing the cache can
never reset the quota."""

from __future__ import annotations

import os
from collections.abc import Mapping
from pathlib import Path


def _dir(env: Mapping[str, str], override: str, xdg: str, fallback: str) -> Path:
    if env.get(override):
        return Path(env[override]).expanduser()
    base = env.get(xdg)
    return (Path(base) if base else Path.home() / fallback) / "dlens"


def cache_path(env: Mapping[str, str] | None = None) -> Path:
    env = os.environ if env is None else env
    return _dir(env, "DLENS_CACHE_DIR", "XDG_CACHE_HOME", ".cache") / "llm.sqlite"


def quota_path(env: Mapping[str, str] | None = None) -> Path:
    env = os.environ if env is None else env
    # DLENS_STATE_DIR is used as-is; XDG_STATE_HOME / ~/.local/state get a dlens/ subdir.
    return _dir(env, "DLENS_STATE_DIR", "XDG_STATE_HOME", ".local/state") / "quota.sqlite"
