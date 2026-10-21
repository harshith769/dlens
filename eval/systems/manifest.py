"""The run manifest (metrics-design M15), shared by every system runner (S0, S1, S4).

A manifest is one JSON file beside a records file. ``metrics.py`` refuses to score records without
one. The base fields are the same for every system; each runner adds its own settings (S0: depth
and linker; S1: prompt hashes, retrieval and budget settings; S4: prompt and agent-code hashes,
tool settings, cache). S1 and S4 also record ``model_identity`` and ``quota`` (S13; manifest-only,
no runner behaviour changes).
"""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
from collections.abc import Mapping
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from dlens.agent.llm.base import LLMClient, Provider

ROOT = Path(__file__).resolve().parents[2]
QUESTIONS = ROOT / "eval" / "questions" / "dev.jsonl"


def git_commit() -> str | None:
    try:
        return subprocess.run(
            ["git", "rev-parse", "HEAD"], cwd=ROOT, capture_output=True, text=True, check=True
        ).stdout.strip()
    except (OSError, subprocess.CalledProcessError):
        return None


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()


def base_manifest(
    *,
    system: str,
    provider: str,
    model: str,
    records_file: Path,
    record_count: int,
    required: list[str],
    questions: Path = QUESTIONS,
    view: str = "validated",
) -> dict[str, Any]:
    """The M15 fields every manifest has. ``questions_file`` is written relative to the repo."""
    return {
        "system": system,
        "view": view,
        "provider": provider,
        "model": model,
        "records_file": records_file.name,
        "record_count": record_count,
        "questions_file": questions.resolve().relative_to(ROOT).as_posix(),
        "questions_sha256": sha256_text(questions.read_text()),
        "git_commit": git_commit(),
        "required": required,
    }


def manifest_path(records_file: Path) -> Path:
    """``<name>.jsonl`` → ``<name>.manifest.json`` (what ``metrics.manifest_path`` reads)."""
    return records_file.with_name(records_file.stem + ".manifest.json")


def write_manifest(records_file: Path, manifest: Mapping[str, Any]) -> Path:
    path = manifest_path(records_file)
    path.write_text(json.dumps(manifest, indent=1, sort_keys=True) + "\n")
    return path


def is_cloud(provider: Provider) -> bool:
    """Ollama and an OpenAI-compatible endpoint on localhost are local; everything else is cloud.
    (S4's copy; ``s1.py`` keeps its own, frozen.)"""
    if provider.name == "ollama":
        return False
    return not bool(getattr(provider, "local", False))


def _ollama_host() -> str:
    host = os.environ.get("OLLAMA_HOST", "http://localhost:11434")
    return host if host.startswith("http") else f"http://{host}"


def model_identity(provider: Any) -> dict[str, Any]:
    """What pins the model beyond its tag (owner, S12b STOP 2; shared by S1 and S4 in S13).

    Ollama: the full model digest, the server version, the Modelfile's default parameters and the
    sampling settings sent with every call (temperature 0, no seed, num_ctx). Raises if Ollama
    can't be asked: a run must not start with an unrecorded model.
    Gemini (pilot-design §2): the temperature and the ``thinkingConfig`` exactly as the request
    carries them; ``null`` means the request has no ``thinkingConfig`` field, so the API applies
    the model's own default level."""
    out: dict[str, Any] = {
        "provider": provider.name,
        "model": provider.model,
        "sampling": {**dict(provider.params), "seed": None},  # no seed is sent
    }
    if provider.name == "gemini":
        level = getattr(provider, "thinking_level", None)
        return out | {
            "request": {
                "temperature": provider.temperature,
                "thinking_config": {"thinking_level": level} if level else None,
                "thinking_config_note": (
                    "sent as set"
                    if level
                    else "not sent: no thinkingConfig in the request (the model's default level)"
                ),
            }
        }
    if provider.name != "ollama":
        return out
    import httpx

    client = provider._client
    digests = {m.model: m.digest for m in client.list().models}
    if provider.model not in digests:
        raise SystemExit(f"model {provider.model!r} is not pulled in Ollama")
    version = httpx.get(f"{_ollama_host()}/api/version", timeout=10).json()["version"]
    return out | {
        "digest": digests[provider.model],
        "ollama_version": version,
        "modelfile_parameters": client.show(provider.model).parameters,
    }


def quota_info(client: LLMClient) -> dict[str, Any]:
    """The daily cap the run ran under (S13, owner): the effective budget, the counter's day key
    and where the counter lives. The counter is one SQLite file per state dir, keyed by
    (provider, Pacific calendar day) and shared by every process using it, so the cap holds
    across runs on one day. No absolute path: a store outside the repo is named only."""
    from dlens.agent.llm.quota import PACIFIC

    quota = client.quota
    name = client.provider.name
    store = Path(quota.path).resolve().parent
    return {
        "provider": name,
        "daily_budget": quota.budgets.get(name),
        "day_basis": "calendar day, America/Los_Angeles (the counter's key)",
        "day_key": datetime.now(PACIFIC).date().isoformat(),
        "used_today": quota.used(name),
        "store": store.relative_to(ROOT).as_posix()
        if store.is_relative_to(ROOT)
        else "user state dir (outside the repo)",
    }
