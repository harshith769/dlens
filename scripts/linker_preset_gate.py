"""S08 gate 8a: replay the recorded demo presets with the CURRENT linker, no LLM call.

uv run python scripts/linker_preset_gate.py [--json out.json]

For each preset: every non-resolve_entity payload must be identical to the recording;
resolve_entity's top-1 and ``ambiguous`` must be identical; the recorded final answer must
re-validate on the rebuilt ledger. Prints one row per preset and the resolve_entity diffs.
Exit 1 if any check fails.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from dlens.agent.validator import validate
from dlens.ui import demo


def check(p: demo.Preset, graph: Any, project_dir: Path) -> dict[str, Any]:
    run, box = demo.replay(p, graph, project_dir)
    recorded = [r for s in p.record.steps for r in s.results if not r.deduped]
    row: dict[str, Any] = {"id": p.id, "other_payloads_identical": True, "resolve": [], "ok": True}
    for got, want in zip(box.log, recorded, strict=True):
        if got.tool != "resolve_entity":
            if got.llm_payload != want.llm_payload:
                row["other_payloads_identical"] = row["ok"] = False
            continue
        old, new = want.llm_payload, got.llm_payload
        o_top = (old["candidates"] or [{}])[0].get("id")
        n_top = (new["candidates"] or [{}])[0].get("id")
        same = o_top == n_top and old["ambiguous"] == new["ambiguous"]
        row["ok"] &= same
        row["resolve"].append({
            "text": got.args.get("text"), "top1_old": o_top, "top1_new": n_top,
            "ambiguous_old": old["ambiguous"], "ambiguous_new": new["ambiguous"], "same": same,
            "old": [(c["id"], c["match"], c["score"]) for c in old["candidates"]],
            "new": [(c["id"], c["match"], c["score"]) for c in new["candidates"]],
            "new_extra_keys": sorted(set(new) - set(old)),
        })  # fmt: skip
    result = validate(run.answer, box, p.question)
    row["revalidates"] = result.passed
    row["ok"] &= result.passed
    return row


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--json")
    args = ap.parse_args()
    project_dir = demo.projects({})[demo.PROJECT]
    graph = demo.load_graph(project_dir)
    rows = [check(p, graph, project_dir) for p in demo.load_presets(demo.presets_dir({}))]
    for r in rows:
        print(f"{r['id']}: ok={r['ok']} other_payloads_identical={r['other_payloads_identical']} "
              f"revalidates={r['revalidates']} resolve_calls={len(r['resolve'])}")  # fmt: skip
        for d in r["resolve"]:
            print(f"   {d['text']!r}: top1 {d['top1_old']} -> {d['top1_new']}; ambiguous "
                  f"{d['ambiguous_old']} -> {d['ambiguous_new']}")  # fmt: skip
            print(f"      old {d['old']}\n      new {d['new']}  (+{d['new_extra_keys']})")
    if args.json:
        Path(args.json).write_text(json.dumps(rows, indent=1))
    return 0 if all(r["ok"] for r in rows) else 1


if __name__ == "__main__":
    sys.exit(main())
