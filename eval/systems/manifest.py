"""The run manifest (metrics-design M15), shared by every system runner (S0, S1, S4).

A manifest is one JSON file beside a records file. ``metrics.py`` refuses to score records without
one. The base fields are the same for every system; each runner adds its own settings (S0: depth
and linker; S1: prompt hashes, retrieval and budget settings; S4: prompt and agent-code hashes,
tool settings, cache).
"""

from __future__ import annotations

import hashlib
import json
import subprocess
from collections.abc import Mapping
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from dlens.agent.llm.base import Provider

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
