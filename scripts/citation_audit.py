"""Citation audit (S11, owner decision): does each chunk's cited line range contain the chunk's own
entity name? Report only, no scores.

For every chunk in the synthetic_shop index, the range a ledger would cite (``chunk_citation``,
and for reference the chunk's raw metadata) is read from disk and checked for the chunk's entity
name, as a whole word, case-insensitive:

* column card (SQL, YAML description or seed CSV): the column's bare name;
* model chunk: the model name or a column the model defines (names from the model's own column
  cards: YAML/catalog, never parser output);
* doc chunk: the entity it describes (model description: the model name; exposure: its name;
  README: none, so not applicable).

A citation's ``level`` is counted too: star pass-through column cards keep their range and are
cited at ``level: star`` (M7 checks such lines for ``*``, not for the name).

Writes ``eval/reports/citation_audit.{md,json}``. ``--before`` adds the counts of an earlier run
(a JSON written by this script) as a "before" column.

    uv run --extra retrieval python scripts/citation_audit.py [--before old.json]
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from collections import defaultdict
from collections.abc import Callable, Iterable, Mapping
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "eval"))

from dlens.retrieval.chunks import Chunk  # noqa: E402
from dlens.retrieval.citation import chunk_citation  # noqa: E402

PROJECT = ROOT / "corpora" / "synthetic_shop"
INDEX = PROJECT / "target" / "dlens_index" / "chunks.jsonl"
OUT = ROOT / "eval" / "reports" / "citation_audit"
EXAMPLES = 3


def kind_of(c: Chunk) -> str:
    ext = c.file.rsplit(".", 1)[-1]
    if c.kind == "column":
        return {"csv": "column card (seed CSV)", "sql": "column card (SQL)"}.get(
            ext, "column card (YAML description)"
        )
    if c.kind == "model":
        return "model chunk (SQL)"
    return f"doc chunk ({c.doc_kind})"


def entity_names(c: Chunk, columns_by_model: Mapping[str, set[str]]) -> set[str]:
    """The names a chunk's citation should contain; empty = not applicable."""
    last = (c.model or "").rsplit(".", 1)[-1]
    if c.kind == "column":
        return {(c.column or "").rsplit(".", 1)[-1]}
    if c.kind == "model":
        return {last, *columns_by_model.get(c.model or "", set())}
    if c.doc_kind in ("model_description", "source_description", "exposure", "docs_block"):
        return {last} if last else set()
    return set()


def contains(text: str, names: Iterable[str]) -> bool:
    return any(re.search(rf"(?<!\w){re.escape(n)}(?!\w)", text, re.I) for n in names if n)


def cited_lines(cite: Mapping[str, Any], project: Path) -> str:
    lines = (project / cite["file"]).read_text(encoding="utf-8", errors="replace").splitlines()
    return "\n".join(lines[cite["line_start"] - 1 : cite["line_end"]])


def raw_citation(c: Chunk, project: Path) -> dict[str, Any]:
    return {"file": c.file, "line_start": c.line_start, "line_end": c.line_end, "level": c.level}


def audit(
    chunks: list[Chunk],
    project: Path,
    cite: Callable[[Chunk, Path], Mapping[str, Any]],
) -> dict[str, Any]:
    columns_by_model: dict[str, set[str]] = defaultdict(set)
    for c in chunks:
        if c.kind == "column" and c.model and c.column:
            columns_by_model[c.model].add(c.column.rsplit(".", 1)[-1])
    out: dict[str, dict[str, Any]] = {}
    for c in sorted(chunks, key=lambda c: (kind_of(c), c.file, c.line_start, c.id)):
        k = out.setdefault(
            kind_of(c), {"contains": 0, "missing": 0, "n/a": 0, "star": 0, "examples": []}
        )
        names = entity_names(c, columns_by_model)
        if not names:
            k["n/a"] += 1
            continue
        ci = cite(c, project)
        k["star"] += ci["level"] == "star"
        if contains(cited_lines(ci, project), names):
            k["contains"] += 1
        else:
            k["missing"] += 1
            if len(k["examples"]) < EXAMPLES:
                k["examples"].append(
                    {
                        "id": c.id,
                        "title": c.title,
                        "file": ci["file"],
                        "lines": [ci["line_start"], ci["line_end"]],
                        "names": sorted(names)[:3],
                    }  # fmt: skip
                )
    return out


def star_edge_check(chunks: list[Chunk], graph: Any, project: Path) -> dict[str, Any]:
    """For each column card the ledger cites at level star, the engine's edge into that column
    (S4's provenance citation) must cite the same file and lines at the same level. Reads the
    graph; S1 never does."""
    from dlens.agent.tools.provenance import Provenance

    prov = Provenance(graph, project)
    into: dict[str, list[Any]] = defaultdict(list)
    for e in graph.edges():
        into[e.to_column].append(e)
    stars = [c for c in chunks if chunk_citation(c, project)["level"] == "star"]
    match, mismatched = 0, []
    for c in stars:
        mine = chunk_citation(c, project)
        theirs = [prov.edge_citation(e).model_dump() for e in into.get(c.column or "", [])]
        if mine in theirs:
            match += 1
        else:
            mismatched.append({"id": c.id, "column": c.column, "edges": theirs})
    out: dict[str, Any] = {"star cards": len(stars), "match": match}
    if mismatched:
        out["mismatched"] = mismatched
    return out


def render(result: Mapping[str, Any], before: Mapping[str, Any] | None) -> str:
    out = [
        "# Citation audit: does each chunk's cited range contain its own name? (S11)",
        "",
        "Report only, no scores. Generated by `scripts/citation_audit.py` over the synthetic_shop "
        "index. The check is whole-word, case-insensitive. Entity name: a column card's bare "
        "column name; a model chunk's model name or any column the model defines (from its own "
        "column cards); a doc chunk's described entity (README: n/a). **ledger** is what S1's "
        "ledger cites (`dlens.retrieval.citation.chunk_citation`); **chunk metadata** is the "
        "chunk's own range, which the chunker, the ids and the linker keep unchanged. "
        "\"level star N\": N of the missing citations are cited at `level: star`.",
        "",
    ]
    cols = ["chunk metadata", *(["ledger, before"] if before else []), "ledger"]
    out += [
        "| chunk kind | " + " | ".join(f"{c}: contains / missing" for c in cols) + " |",
        "|---|" + "---|" * len(cols),
    ]
    for kind in sorted(result["ledger"]):
        cells = [result["chunk_metadata"][kind]]
        if before:
            cells.append(before["ledger"].get(kind, {"contains": 0, "missing": 0}))
        cells.append(result["ledger"][kind])
        out.append(
            f"| {kind} | "
            + " | ".join(
                f"{x['contains']} / {x['missing']}"
                + (f" (n/a {x['n/a']})" if x.get("n/a") else "")
                + (f" (level star {x['star']})" if x.get("star") else "")
                for x in cells
            )
            + " |"
        )
    out += [
        "",
        "## Not fixable by the helper (left unchanged)",
        "",
        "- **column card (SQL), star pass-through**: the card cites the `select *` line that "
        "passes the column through, so the cited line doesn't contain the name. The range is "
        "kept and the ledger cites it at **`level: star`**, the rule S4's provenance applies: "
        "the cited range contains `*` and doesn't name the column (cited range, not "
        "statement). Metrics M7 then checks the lines for `*` (pre-merge fix, S11).",
        "- **model chunk (SQL)** with no entity name: `fct_payment_events` is a one-line "
        "`select * from {{ ref(...) }}`, and a 40-line fallback window of `fct_customer_cohorts` "
        "holds only its `from` / `join` / `group by` clauses. A chunk's range is its own text, and "
        "widening it would cite lines the model was never shown.",
    ]
    for label, key in (("ledger", "ledger"), ("chunk metadata", "chunk_metadata")):
        missing = {k: v for k, v in result[key].items() if v["missing"]}
        out += ["", f"## Missing, {label} (up to {EXAMPLES} examples per kind)", ""]
        if not missing:
            out.append("None.")
        for kind, v in sorted(missing.items()):
            out.append(f"- **{kind}** ({v['missing']}):")
            out += [
                f"  - `{e['id']}` {e['title']}: `{e['file']}:{e['lines'][0]}-{e['lines'][1]}` "
                f"lacks {', '.join(e['names'])}"
                for e in v["examples"]
            ]
    if "star_edge_check" in result:
        chk = result["star_edge_check"]
        out += [
            "",
            "## Star cards vs the engine's pass-through edges",
            "",
            f"{chk['match']} of {chk['star cards']} star column cards have the same file, lines "
            "and level as S4's provenance citation of the engine's edge into that column (graph "
            "read by this script only).",
        ]
        out += [f"- mismatch: `{m['id']}` {m['column']}" for m in chk.get("mismatched", [])]
    return "\n".join(out) + "\n"


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--index", type=Path, default=INDEX)
    ap.add_argument("--out", type=Path, default=OUT)
    ap.add_argument("--before", type=Path, default=None)
    ns = ap.parse_args(argv)
    chunks = [Chunk.from_json(json.loads(x)) for x in ns.index.read_text().splitlines()]
    result = {
        "chunks": len(chunks),
        "chunk_metadata": audit(chunks, PROJECT, raw_citation),
        "ledger": audit(chunks, PROJECT, chunk_citation),
    }
    graph_target = PROJECT / "target"
    if (graph_target / "manifest.json").is_file():
        from dlens.graph import build_graph_from_artifacts

        graph = build_graph_from_artifacts(graph_target)[0]
        result["star_edge_check"] = star_edge_check(chunks, graph, PROJECT)
    before = json.loads(ns.before.read_text()) if ns.before else None
    ns.out.parent.mkdir(parents=True, exist_ok=True)
    ns.out.with_suffix(".json").write_text(json.dumps(result, indent=1, sort_keys=True) + "\n")
    ns.out.with_suffix(".md").write_text(render(result, before))
    print(render(result, before))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
