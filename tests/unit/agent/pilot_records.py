"""Dev cases from the committed S4 pilot records, replayed without a model (S13b post-pilot fixes).

A record keeps every tool result the loop logged (``llm_payload``, ``side_records``), the first
draft and the regenerated draft. ``ledger`` rebuilds the question's ledger from them, exactly as
``Toolbox.call`` registers ids, on the synthetic_shop graph built from the committed fixture
artifacts (available in CI; edge ids are content hashes, so they match the run's). Citations come
from the recorded side records and are checked against the committed corpus files. The records
are frozen pilot data: read only, never rewritten.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from functools import cache
from pathlib import Path
from typing import Any

from dlens.agent.answer import Answer, AnswerDraft, attach
from dlens.agent.tools.toolbox import ToolResult, _ids_in
from dlens.graph import LineageGraph, build_graph_from_artifacts

ROOT = Path(__file__).resolve().parents[3]
SS_TARGET = ROOT / "tests" / "fixtures" / "artifacts" / "synthetic_shop"
SS_PROJECT = ROOT / "corpora" / "synthetic_shop"
RECORDS = {
    "qwen": ROOT / "eval/runs/s4/s4-qwen3-4b-instruct-2507-q4-k-m-dev.jsonl",
    "gemini": ROOT / "eval/runs/s4/s4-gemini-3-5-flash-lite-dev.jsonl",
}


@cache
def graph() -> LineageGraph:
    return build_graph_from_artifacts(SS_TARGET)[0]


@cache
def _records(model: str) -> dict[str, str]:
    lines = RECORDS[model].read_text().splitlines()
    return {json.loads(x)["question_id"]: x for x in lines if x.strip()}


def record(qid: str, model: str = "qwen") -> dict[str, Any]:
    """A fresh copy of one committed record."""
    return json.loads(_records(model)[qid])


@dataclass
class RecordLedger:
    """The ``Ledger`` protocol rebuilt from a record's non-deduped tool results, in order."""

    graph: LineageGraph
    project_dir: Path
    log: list[ToolResult] = field(default_factory=list)
    _emitted: dict[str, dict[str, Any]] = field(default_factory=dict)

    @property
    def emitted_ids(self) -> frozenset[str]:
        return frozenset(self._emitted)

    def record(self, item_id: str) -> dict[str, Any] | None:
        return self._emitted.get(item_id)


def ledger(rec: dict[str, Any]) -> RecordLedger:
    led = RecordLedger(graph(), SS_PROJECT)
    for step in rec["steps"]:
        for r in step.get("results") or []:
            if r.get("deduped"):
                continue  # the loop never re-runs a deduped call, so it is not in the log
            tr = ToolResult(
                tool=r["tool"],
                args=r.get("args") or {},
                llm_payload=r.get("llm_payload") or {},
                side_records=r.get("side_records") or {},
                code_initiated=bool(r.get("code_initiated")),
                rule=r.get("rule"),
            )
            if not tr.is_error:
                shown = set(_ids_in(tr.llm_payload))
                for kind in ("edges", "excerpts", "facts", "chunks"):
                    for item_id, item in tr.side_records.get(kind, {}).items():
                        if item_id in shown:
                            led._emitted[item_id] = item
            led.log.append(tr)
    return led


def first_answer(rec: dict[str, Any], led: RecordLedger) -> Answer:
    """The first draft as the loop attached it before validation."""
    partial = bool((rec.get("evidence") or {}).get("partial_evidence"))
    return attach(AnswerDraft.model_validate(rec["draft"]), led, partial_evidence=partial)


def regenerate_text(rec: dict[str, Any]) -> str:
    """The regenerated draft's raw JSON, as the model returned it."""
    return str(rec["regenerate_draft_raw"])
