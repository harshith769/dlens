"""Re-attach the citations of committed S1 records under the current ``chunk_citation`` rule
(S11 pre-merge fix: star pass-through cards cite at ``level: star``). No LLM call.

The evidence header shows only a chunk's file and lines, never its level, so a rule change that
moves only levels leaves every prompt, and with it every answer, unchanged. Each citation in
``final_answer.citations`` is recomputed from the index chunk with the same id; ranges must not
move (the script stops if one does). The manifest's ``citation_rule`` text and sha256 are updated
and the re-attachment is noted in it. Nothing else in the records changes.

    uv run --extra retrieval python scripts/s1_reattach_citations.py
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "eval"))

from dlens.retrieval.chunks import Chunk  # noqa: E402
from dlens.retrieval.citation import chunk_citation  # noqa: E402
from systems.manifest import sha256_text  # noqa: E402
from systems.s1 import CITATION_RULE  # noqa: E402

PROJECT = ROOT / "corpora" / "synthetic_shop"
INDEX = PROJECT / "target" / "dlens_index" / "chunks.jsonl"
RECORDS = ROOT / "eval" / "runs" / "s1" / "s1-qwen3-4b-instruct-2507-q4-k-m-dev.jsonl"


def main() -> int:
    chunks = {
        c.id: c for c in (Chunk.from_json(json.loads(x)) for x in INDEX.read_text().splitlines())
    }
    out, changed = [], 0
    for line in RECORDS.read_text().splitlines():
        rec = json.loads(line)
        cites = (rec.get("final_answer") or {}).get("citations") or {}
        for cid, old in cites.items():
            new = chunk_citation(chunks[cid], PROJECT)
            if {k: new[k] for k in ("file", "line_start", "line_end")} != {
                k: old[k] for k in ("file", "line_start", "line_end")
            }:
                raise SystemExit(f"{rec['run_id']} {cid}: range moved; this needs an S1 re-run")
            if new["level"] != old["level"]:
                changed += 1
                cites[cid] = {**old, "level": new["level"]}
        out.append(json.dumps(rec, sort_keys=True) + "\n")
    RECORDS.write_text("".join(out))
    mpath = RECORDS.with_name(RECORDS.name.replace(".jsonl", ".manifest.json"))
    m = json.loads(mpath.read_text())
    m["prompt_sha256"]["citation_rule"] = sha256_text(CITATION_RULE)
    m["retrieval"]["citation_rule"] = CITATION_RULE
    m["citations_reattached"] = (
        "citation levels re-attached under chunk_citation v3 (star pass-through cards: level "
        "star) by scripts/s1_reattach_citations.py; no LLM call, ranges and answers unchanged"
    )
    mpath.write_text(json.dumps(m, indent=1, sort_keys=True) + "\n")
    print(f"{changed} citation levels changed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
