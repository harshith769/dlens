"""Draft logging: one JSONL record per agent run (spec §8: log the pre-validation draft).

Records go to ``runs_dir()/YYYY-MM-DD.jsonl``: ``$DLENS_RUN_DIR`` as-is, else
``$XDG_STATE_HOME/dlens/runs``, else ``~/.local/state/dlens/runs``. They hold what the model saw
(``llm_payload``) and what code kept (``side_records``) for every tool call, the raw draft before
validation and the validation result, so the no-validator ablation can be replayed offline.
"""

from __future__ import annotations

import os
from collections.abc import Mapping
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, Field

SCHEMA_VERSION = 1


def runs_dir(env: Mapping[str, str] | None = None) -> Path:
    env = os.environ if env is None else env
    if env.get("DLENS_RUN_DIR"):
        return Path(env["DLENS_RUN_DIR"]).expanduser()
    base = env.get("XDG_STATE_HOME")
    return (Path(base) if base else Path.home() / ".local/state") / "dlens" / "runs"


class StepResult(BaseModel):
    tool: str
    args: dict[str, Any]
    llm_payload: dict[str, Any]
    side_records: dict[str, Any] = Field(default_factory=dict)
    deduped: bool = False
    duplicate_of: int | None = None  # index in the toolbox log of the original call


class Step(BaseModel):
    index: int
    phase: Literal["tool", "answer", "repair", "code"]
    est_input_tokens: int = 0
    input_tokens: int = 0  # provider-reported usage
    output_tokens: int = 0
    cached: bool = False
    latency_ms: float = 0.0
    text: str = ""
    tool_calls: list[dict[str, Any]] = Field(default_factory=list)
    results: list[StepResult] = Field(default_factory=list)
    error: str | None = None

    @property
    def is_llm_call(self) -> bool:
        return self.phase != "code"


class RunRecord(BaseModel):
    schema_version: int = SCHEMA_VERSION
    run_id: str
    started_at: str
    question: str
    project: str = ""
    provider: str = ""
    model: str = ""
    params: dict[str, Any] = Field(default_factory=dict)
    steps: list[Step] = Field(default_factory=list)
    compactions: list[dict[str, Any]] = Field(default_factory=list)
    ambiguity: dict[str, Any] | None = None  # {mode, candidates, downstream}
    evidence: dict[str, Any] = Field(default_factory=dict)  # {ids, dropped_ids, partial_evidence}
    draft_raw: str | None = None  # the answer-phase text exactly as the model returned it
    draft: dict[str, Any] | None = None  # parsed AnswerDraft, pre-validation
    clarification: dict[str, Any] | None = None
    validation: dict[str, Any] | None = None
    final_answer: dict[str, Any] | None = None
    stop_reason: str = ""
    error: str | None = None
    timings: dict[str, float] = Field(default_factory=dict)
    tokens: dict[str, int] = Field(default_factory=dict)

    @property
    def llm_calls(self) -> int:
        return sum(s.is_llm_call for s in self.steps)


def now_iso() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


class RunLogger:
    def __init__(self, directory: Path) -> None:
        self.directory = directory

    def path_for(self, record: RunRecord) -> Path:
        return self.directory / f"{record.started_at[:10]}.jsonl"

    def write(self, record: RunRecord) -> Path:
        path = self.path_for(record)
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as fh:
            fh.write(record.model_dump_json() + "\n")
        return path
