"""Compare engine edges with a hand-written gold spec (``lineage_spec.yml``) on (from, to) pairs.

The gold spec uses short ``table.column`` ids. Engine ids are converted with ``short_id``; this
module never writes the spec. Loading YAML is left to callers, so pyyaml stays a dev dependency.
"""

from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass

from dlens.lineage.models import Edge, IndirectEdge, short_id


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


@dataclass(frozen=True)
class Score:
    precision: float
    recall: float
    f1: float
    engine: int
    gold: int
    matched: int


def _score(ours: set[tuple[str, str, str]], theirs: set[tuple[str, str, str]]) -> Score:
    matched = len(ours & theirs)
    p = matched / len(ours) if ours else 0.0
    r = matched / len(theirs) if theirs else 0.0
    f1 = 2 * p * r / (p + r) if p + r else 0.0
    return Score(p, r, f1, len(ours), len(theirs), matched)


@dataclass(frozen=True)
class IndirectReport:
    overall: Score
    by_type: dict[str, Score]
    by_model: dict[str, Score]  # by target model (short name)
    missing: list[tuple[str, str, str]]  # (from, to, type) in the gold, not produced
    extra: list[tuple[str, str, str]]  # (from, to, type) produced, not in the gold


def compare_indirect(
    engine: Iterable[IndirectEdge], gold: Iterable[tuple[str, str, str]]
) -> IndirectReport:
    """Engine indirect edges vs gold (from, to, type) triples in short ids, e.g. the pairs of
    ``dlens.gold_spec.expand_indirect``. A pair with two types counts once per type."""
    ours = {(short_id(e.from_column), short_id(e.to_column), str(e.kind)) for e in engine}
    theirs = {(f.lower(), t.lower(), k) for f, t, k in gold}

    def split(key: Callable[[tuple[str, str, str]], str]) -> dict[str, Score]:
        return {
            k: _score({x for x in ours if key(x) == k}, {x for x in theirs if key(x) == k})
            for k in sorted({key(x) for x in ours | theirs})
        }

    return IndirectReport(
        overall=_score(ours, theirs),
        by_type=split(lambda x: x[2]),
        by_model=split(lambda x: x[1].split(".")[0]),
        missing=sorted(theirs - ours),
        extra=sorted(ours - theirs),
    )
