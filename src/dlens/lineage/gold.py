"""Compare engine edges with a hand-written gold spec (``lineage_spec.yml``) on (from, to) pairs.

The gold spec uses short ``table.column`` ids. Engine ids are converted with ``short_id``; this
module never writes the spec. Loading YAML is left to callers, so pyyaml stays a dev dependency.
"""

from collections.abc import Iterable, Mapping
from dataclasses import dataclass

from dlens.lineage.models import Edge, short_id


@dataclass(frozen=True)
class GoldReport:
    precision: float
    recall: float
    f1: float
    kind_accuracy: float  # over matched (from, to) pairs
    matched: int
    missing: list[tuple[str, str, str]]  # (from, to, gold kind) not produced by the engine
    extra: list[tuple[str, str, str]]  # (from, to, engine kind) not in the gold spec
    kind_mismatches: list[tuple[str, str, str, str]]  # (from, to, gold kind, engine kind)


def compare(engine: Iterable[Edge], gold: Iterable[Mapping[str, str]]) -> GoldReport:
    ours = {(short_id(e.from_column), short_id(e.to_column)): str(e.kind) for e in engine}
    theirs = {(g["from"].lower(), g["to"].lower()): g["kind"] for g in gold}
    matched = ours.keys() & theirs.keys()
    precision = len(matched) / len(ours) if ours else 0.0
    recall = len(matched) / len(theirs) if theirs else 0.0
    f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0
    mismatches = sorted((*k, theirs[k], ours[k]) for k in matched if theirs[k] != ours[k])
    return GoldReport(
        precision=precision,
        recall=recall,
        f1=f1,
        kind_accuracy=(len(matched) - len(mismatches)) / len(matched) if matched else 0.0,
        matched=len(matched),
        missing=sorted((*k, theirs[k]) for k in theirs.keys() - ours.keys()),
        extra=sorted((*k, ours[k]) for k in ours.keys() - theirs.keys()),
        kind_mismatches=mismatches,
    )
