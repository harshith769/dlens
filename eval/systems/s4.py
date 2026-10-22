"""S4 runner: the DLens agent (graph tools + validator) on the dev questions (s12-design A4).

Shaped like ``s1.py``: one ``Toolbox`` and ``Agent`` per run, records with a relative project path
and each question's id, and a manifest (metrics-design M15) with the prompt and code hashes the
spec §11.7 freeze needs, the tool settings and the cache setup the latency numbers depend on.
Metrics joins records to questions on the exact text (M12); the runner checks every record's
``question_id`` against that join before writing.

    DLENS_PROVIDER=ollama DLENS_CACHE_DIR=eval/cache uv run --extra agent --extra retrieval \\
        python eval/systems/s4.py

The linker's hybrid stage is on by default (s12-design B4 (a)): the runner opens the S07 index,
which needs the retrieval extra. ``--no-hybrid`` runs without it. A cloud provider is refused
unless ``--allow-cloud`` is passed.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))  # eval/: systems.* as a script

from dlens.agent import loop, prompts
from dlens.agent.answer import DRAFT_SCHEMA
from dlens.agent.llm.base import LLMClient
from dlens.agent.loop import _DEFAULTS, MAX_LLM_CALLS, MAX_TOOL_PHASE_CALLS, Agent
from dlens.agent.runlog import RunRecord
from dlens.agent.tools import TOOL_SPECS, Toolbox
from dlens.agent.tools.budget import MAX_RESULT_TOKENS
from systems.manifest import (
    QUESTIONS,
    ROOT,
    base_manifest,
    is_cloud,
    model_identity,
    quota_info,
    sha256_text,
    write_manifest,
)

if TYPE_CHECKING:
    from dlens.graph import LineageGraph
    from dlens.retrieval.index import SearchIndex

CORPUS = "corpora/synthetic_shop"
OUT = ROOT / "eval" / "runs" / "s4"
SYSTEM = "s4"
AGENT_DIR = ROOT / "src" / "dlens" / "agent"


def slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")


# ---------------------------------------------------------------------------- hashes (§11.7)
def prompt_hashes(toolbox: Toolbox | None = None) -> dict[str, str]:
    """sha256 of every text the agent sends besides the question and tool results. The tool
    prompt and specs are the ones ``toolbox`` sends (with an index: search_docs, B4)."""
    directives = "\n".join(
        [
            prompts.chain_directive(["A", "B"], "B"),
            prompts.per_candidate_directive(["A", "B"]),
            prompts.PARTIAL_DIRECTIVE,
            prompts.clarification_question("Q"),
            prompts.answer_user("Q", "E", ["D"]),
        ]
    )
    docs = toolbox is not None and toolbox.has_docs
    tool_specs = toolbox.specs() if toolbox is not None else TOOL_SPECS
    specs = [s.model_dump(mode="json") for s in tool_specs]
    return {
        "tool_system": sha256_text(prompts.tool_system(docs)),
        "answer_system": sha256_text(prompts.ANSWER_SYSTEM),
        "draft_schema": sha256_text(json.dumps(DRAFT_SCHEMA, sort_keys=True)),
        "answer_repair": sha256_text(prompts.ANSWER_REPAIR),
        "tool_repair": sha256_text(prompts.TOOL_REPAIR),
        "regenerate": sha256_text(prompts.REGENERATE),
        "directives": sha256_text(directives),
        "tool_specs": sha256_text(json.dumps(specs, sort_keys=True)),
    }


def agent_code_sha256(root: Path = AGENT_DIR) -> str:
    """One sha256 over ``src/dlens/agent/**/*.py`` (sorted relative paths and contents): the
    validator rules, tools and loop together."""
    h = hashlib.sha256()
    for path in sorted(root.rglob("*.py")):
        h.update(path.relative_to(root).as_posix().encode() + b"\0")
        h.update(path.read_bytes() + b"\0")
    return h.hexdigest()


def tool_settings() -> dict[str, Any]:
    return {
        "max_llm_calls": MAX_LLM_CALLS,
        "max_tool_phase_calls": MAX_TOOL_PHASE_CALLS,
        "max_result_tokens": MAX_RESULT_TOKENS,
        # s12-design A6: the answer phase trims to cap - regenerate_reserve
        "regenerate_reserve": loop.REGENERATE_RESERVE,
        "max_regenerate_failures": loop.MAX_REGENERATE_FAILURES,
        "regen_clip_chars": {
            "fact": loop.REGEN_FACT_CHARS,
            "item": loop.REGEN_ITEM_CHARS,
            "message": loop.REGEN_MESSAGE_CHARS,
        },
        "defaults": {name: dict(args) for name, args in sorted(_DEFAULTS.items())},
    }


# ---------------------------------------------------------------------------- run
def question_ids(questions: Sequence[Mapping[str, Any]]) -> dict[str, str]:
    """Exact question text -> id: the M12 join, from the runner's side."""
    return {q["question"]: q["id"] for q in questions}


def check_ids(records: Sequence[RunRecord], questions: Sequence[Mapping[str, Any]]) -> None:
    """Every record's ``question_id`` must be the id metrics' exact-text join gives it."""
    by_text = question_ids(questions)
    bad = [
        (r.question_id, by_text.get(r.question))
        for r in records
        if by_text.get(r.question) != r.question_id
    ]
    if bad:
        raise ValueError(f"question_id does not match the text join: {bad[:3]}")


def run(agent: Agent, questions: Sequence[Mapping[str, Any]], log: Any = None) -> list[RunRecord]:
    out: list[RunRecord] = []
    for i, q in enumerate(questions, 1):
        rec = agent.ask(q["question"], question_id=q["id"]).record
        rec.run_id = f"{SYSTEM}-{q['id']}"
        out.append(rec)
        if log is not None:
            print(
                f"[{i}/{len(questions)}] {q['id']} calls={rec.tokens.get('llm_calls', 0)} "
                f"cache={rec.cache} {rec.stop_reason or '-'}"
                + (f" error={rec.error[:80]!r}" if rec.error else ""),
                file=log,
            )
        if (rec.error or "").startswith("QuotaExceeded"):  # the rest is missing (M12)
            break
    check_ids(out, questions)
    return out


def _cache_dir(client: LLMClient) -> str:
    """The response cache's directory relative to the repo (never an absolute local path)."""
    path = Path(client.cache.path).resolve().parent
    return path.relative_to(ROOT).as_posix() if path.is_relative_to(ROOT) else "outside the repo"


def manifest(
    records: Sequence[RunRecord],
    records_file: Path,
    agent: Agent,
    index: SearchIndex | None,
    index_status: str,
    questions: Path = QUESTIONS,
    allow_cloud: bool = False,
    identity: dict[str, Any] | None = None,
) -> dict[str, Any]:
    import metrics

    prov = agent.client.provider
    steps = [s for r in records for s in r.steps if s.is_llm_call]
    hits = sum(s.cached for s in steps)
    return {
        **base_manifest(
            system=f"{SYSTEM}-{slug(prov.model)}",
            provider=prov.name,
            model=prov.model,
            records_file=records_file,
            record_count=len(records),
            required=[r.question_id or "" for r in records],
            questions=questions,
            view="raw|validated|augmented",
        ),
        "date": datetime.now(UTC).date().isoformat(),
        "metrics_versions": {"design": metrics.DESIGN_VERSION, "metrics": metrics.__version__},
        "params": dict(prov.params),
        "model_identity": identity if identity is not None else model_identity(prov),
        "allow_cloud": allow_cloud,
        "quota": quota_info(agent.client),
        "hybrid": index is not None,
        "index_key": dict(index.meta.get("key") or {}) if index is not None else None,
        "index_status": index_status,
        "prompt_sha256": prompt_hashes(agent.toolbox),
        "agent_code_sha256": agent_code_sha256(),
        "tool_settings": tool_settings(),
        "cache": {
            "dir": _cache_dir(agent.client),
            "hits": hits,
            "misses": len(steps) - hits,
            "records": {k: sum(r.cache == k for r in records) for k in ("hit", "miss", "partial")},
        },
        "note": "S4: DLens agent (graph tools + validator); views raw, validated, augmented "
        "(augmented = validated + G1's origin-augmented claims)",
    }


def open_graph(project_dir: Path, hybrid: bool) -> tuple[LineageGraph, SearchIndex | None, str]:
    from dlens.graph import load_or_build

    graph = load_or_build(project_dir)
    if not hybrid:
        return graph, None, "hybrid off (no index)"
    try:
        from dlens.retrieval.dense import get_embedder
        from dlens.retrieval.index import SearchIndex, project_index_dir
    except ImportError as e:
        raise SystemExit(
            f"S4 with hybrid on needs the retrieval extra: uv sync --extra retrieval ({e})"
        ) from e
    from dlens.graph.cache import cache_path

    index, status = SearchIndex.open(
        graph=graph,
        graph_file=cache_path(project_dir),
        target_dir=project_dir / "target",
        project_dir=project_dir,
        index_dir=project_index_dir(project_dir),
        embedder=get_embedder(),
    )
    return graph, index, status


def write_records(records: Sequence[RunRecord], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "".join(json.dumps(r.model_dump(mode="json"), sort_keys=True) + "\n" for r in records)
    )


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawTextHelpFormatter)
    ap.add_argument("--out", type=Path, default=OUT)
    ap.add_argument("--questions", type=Path, default=QUESTIONS)
    ap.add_argument("--limit", type=int, default=None, help="first N questions only (checks)")
    ap.add_argument("--ids", default=None, help="comma-separated question ids (checks)")
    ap.add_argument("--no-hybrid", action="store_true", help="linker without the hybrid stage")
    ap.add_argument(
        "--prefix", default=SYSTEM, help="records file name prefix (S13b diagnostic: s13b)"
    )
    ap.add_argument("--purpose", default=None, help="a 'purpose' line for the manifest")
    ap.add_argument(
        "--allow-cloud",
        action="store_true",
        help="allow a cloud provider (spends quota; never used in S12)",
    )
    ns = ap.parse_args(argv)

    from dlens.agent.llm import make_client

    client = make_client()
    if is_cloud(client.provider) and not ns.allow_cloud:
        print(
            f"s4: provider {client.provider.name!r} is a cloud provider; refusing without "
            "--allow-cloud (it spends quota).",
            file=sys.stderr,
        )
        return 2
    questions = [json.loads(x) for x in ns.questions.read_text().splitlines() if x.strip()]
    if ns.ids:
        wanted = [i.strip() for i in ns.ids.split(",") if i.strip()]
        unknown = sorted(set(wanted) - {q["id"] for q in questions})
        if unknown:
            print(f"s4: unknown question ids {unknown}", file=sys.stderr)
            return 2
        questions = [q for q in questions if q["id"] in set(wanted)]
    if ns.limit is not None:
        questions = questions[: ns.limit]
    project_dir = ROOT / CORPUS
    graph, index, status = open_graph(project_dir, hybrid=not ns.no_hybrid)
    print(f"s4: {status}", file=sys.stderr)
    agent = Agent(client, Toolbox(graph, project_dir, index), project=CORPUS)
    records = run(agent, questions, log=sys.stderr)
    path = ns.out / f"{ns.prefix}-{slug(client.provider.model)}-dev.jsonl"
    write_records(records, path)
    man = manifest(records, path, agent, index, status, ns.questions, ns.allow_cloud)
    if ns.purpose:
        man["purpose"] = ns.purpose
    write_manifest(path, man)
    print(f"s4: {len(records)} records → {path.name}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
