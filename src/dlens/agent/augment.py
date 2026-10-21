"""Coverage completion (spec §8 G1, s12-design B1, ADR 0015/0025): code appends what the tools
returned and the answer left out, as claims with ``origin: augmented``.

* **Trace** (where-from / how-computed wording): every direct input of a traced column (an edge
  into it in a trace_upstream result) that the answer neither names nor cites gets one claim,
  citing that edge.
* **Impact** (affect / change / downstream wording; s12-design B1 (b), the spec §8 note): every
  column of an impact_downstream result's full side set (``side["full"]``, which keeps the columns
  a payload cut) that the answer neither names nor cites, one claim per (depth, kind) group, as
  dotted ids citing their ``via`` edges.

Only tool results already in the run's log are read: G1 never runs a traversal. Nothing is
added to a refusal or a clarification. Augmented claims skip the validator and count only in the
S4-augmented view (metrics M3 rule 5); S4-raw and S4-validated are unchanged.
"""

from __future__ import annotations

import re
from typing import Any

from dlens.agent.answer import Answer, Claim
from dlens.agent.tools import Toolbox
from dlens.agent.tools.provenance import Citation

_DOTTED = re.compile(r"(?<![\w.])([A-Za-z_]\w*\.[A-Za-z_]\w*)(?![\w])")


def _covered(answer: Answer) -> tuple[set[str], set[str]]:
    """(dotted ids the answer writes, lower-case; ids its claims cite)."""
    texts = [answer.answer_text, *(c.text for c in answer.claims)]
    named = {m.lower() for t in texts for m in _DOTTED.findall(t)}
    return named, {i for c in answer.claims for i in c.ids}


def augment(answer: Answer, toolbox: Toolbox, intent: str | None) -> Answer:
    """``answer`` with the augmented claims appended (and their citations); unchanged when
    ``intent`` is not a lineage tool, the answer is refused or a clarification, or nothing is
    missing."""
    if answer.refused or answer.clarification is not None or intent is None:
        return answer
    named, cited = _covered(answer)
    g = toolbox.graph
    claims: list[Claim] = []
    citations: dict[str, Citation] = {}

    def missing(column: str, edge: str) -> bool:
        return g.display_name(column).lower() not in named and edge not in cited

    def cite(edge: str, rec: dict[str, Any]) -> None:
        if rec.get("citation"):
            citations[edge] = Citation.model_validate(rec["citation"])

    done: set[str] = set()
    for r in toolbox.log:
        if r.tool != intent or r.is_error or r.side_records.get("column") in done:
            continue
        target = str(r.side_records.get("column"))
        done.add(target)
        if intent == "trace_upstream":
            for eid, rec in r.side_records.get("edges", {}).items():
                if rec.get("to") != target or rec.get("indirect") or not missing(rec["from"], eid):
                    continue
                src, dst = g.display_name(rec["from"]), g.display_name(target)
                text = f"{src} is a direct input of {dst}."
                claims.append(Claim(text=text, edge_ids=[eid], origin="augmented"))
                cite(eid, rec)
                named.add(src.lower())
        else:
            full = r.side_records.get("full", {})
            groups: dict[tuple[int, str], list[tuple[str, str]]] = {}
            for name, col in full.get("columns", {}).items():
                if missing(col["id"], col["via"]):
                    groups.setdefault((col["depth"], col["label"]), []).append((name, col["via"]))
            for (depth, label), items in sorted(groups.items()):
                names = ", ".join(n for n, _ in items)
                text = f"Also affected at depth {depth} ({label}): {names}."
                vias = list(dict.fromkeys(v for _, v in items))
                claims.append(Claim(text=text, edge_ids=vias, origin="augmented"))
                for v in vias:
                    cite(v, full.get("edges", {}).get(v, {}))
                named.update(n.lower() for n, _ in items)
    if not claims:
        return answer
    return answer.model_copy(
        update={
            "claims": [*answer.claims, *claims],
            "citations": {**answer.citations, **citations},
        }
    )
