"""Record the demo presets with the LOCAL model: demo/presets/<id>.json (full run records).

Usage:  uv run --extra agent python scripts/record_presets.py           # needs Ollama running
        uv run --extra agent python scripts/record_presets.py --fresh   # bypass the LLM cache

Runs the questions in dlens.ui.demo.PRESET_IDS against the demo bundle (not corpora/), so the
recorded citations are the bundle's. Ollama only: any other provider is refused. Like
scripts/dev_report.py the LLM cache defaults to eval/cache, so questions answered there before
replay without a model call; --fresh uses a throwaway cache. Each run is scored with the dev
scoring (dev_report.score); a preset that does not pass is NOT written, and the script exits 1.
The UI replays these files with zero LLM calls (dlens.ui.demo.replay).
"""

from __future__ import annotations

import argparse
import importlib.util
import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _dev_report():  # scripts/ is not a package
    spec = importlib.util.spec_from_file_location("dev_report", ROOT / "scripts" / "dev_report.py")
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawTextHelpFormatter)
    ap.add_argument("--fresh", action="store_true", help="use a throwaway LLM cache")
    ap.add_argument("--only", help="comma-separated preset ids")
    ns = ap.parse_args()
    if (os.environ.get("DLENS_PROVIDER") or "ollama").lower() != "ollama":
        sys.exit("record_presets: presets are recorded with the local ollama provider only.")
    tmp = tempfile.TemporaryDirectory() if ns.fresh else None
    os.environ["DLENS_CACHE_DIR"] = tmp.name if tmp else str(ROOT / "eval" / "cache")

    from dlens.agent.llm import make_client
    from dlens.agent.loop import ask
    from dlens.agent.runlog import RunLogger, runs_dir
    from dlens.agent.tools import Toolbox
    from dlens.lineage import short_id
    from dlens.ui import demo

    dev = _dev_report()
    questions = {q["id"]: q for q in dev.load_questions()}
    project = demo.projects({})[demo.PROJECT]
    graph = demo.load_graph(project)
    client = make_client("ollama")
    logger = RunLogger(runs_dir())
    out = demo.presets_dir({})
    out.mkdir(parents=True, exist_ok=True)
    only = set(ns.only.split(",")) if ns.only else None
    failed = []
    for qid in demo.PRESET_IDS:
        if only and qid not in only:
            continue
        q = questions[qid]
        box = Toolbox(graph, project)
        run = ask(q["question"], client, box, logger, project=demo.PROJECT)

        def edge_of(i: str, box: Toolbox = box) -> tuple[str, str] | None:
            rec = box.record(i)
            return (short_id(rec["from"]), short_id(rec["to"])) if rec and "from" in rec else None

        row = dev.score(
            q, run.answer.model_dump(mode="json"), run.record.model_dump(mode="json"), edge_of
        )
        calls = run.record.llm_calls
        cached = run.record.tokens.get("cached_calls", 0)
        if not row["pass"]:
            failed.append(qid)
            print(f"{qid}: fail ({'; '.join(row['reasons'])}); not written")
            continue
        (out / f"{qid}.json").write_text(demo.preset_json(qid, q["subtype"], run.record))
        print(f"{qid}: PASS  {calls} LLM calls ({cached} cached)  model={run.record.model}")
    if tmp:
        tmp.cleanup()
    if failed:
        print(f"{len(failed)} preset(s) failed: {', '.join(failed)}. Pick others or re-record.")
        return 1
    print(f"wrote {out.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
