"""Parse-quality report over a built graph (``dlens report``). Pure: no dbt, no file access."""

from pydantic import BaseModel

from dlens.graph.graph import LineageGraph
from dlens.lineage import Confidence, ParseQuality


class ModelReport(BaseModel):
    model: str
    quality: ParseQuality
    reason: str | None
    gaps: list[str]
    constants: list[str]
    citation_gaps: list[str] = []


class Totals(BaseModel):
    models_by_quality: dict[str, int]
    edges: int
    edges_by_kind: dict[str, int]
    model_level_citations: int
    indirect_edges: int = 0
    indirect_model_level_citations: int = 0
    low_confidence_edges: int
    deferred_indirect: int
    """Window keys: distinct (from, to) pairs of WINDOW indirect edges. The v0.1 name and line
    are kept so the report reads the same; ModelParse.deferred_indirect is retired (S04)."""
    constants: int


class Report(BaseModel):
    models: list[ModelReport]
    totals: Totals


def build_report(graph: LineageGraph) -> Report:
    models = [
        ModelReport(
            model=uid,
            quality=p.quality,
            reason=p.reason,
            gaps=p.gaps,
            constants=p.constants,
            citation_gaps=p.citation_gaps,
        )
        for uid, p in graph.parse_details().items()
    ]
    edges = graph.edges()
    by_kind: dict[str, int] = {}
    for e in edges:
        by_kind[str(e.kind)] = by_kind.get(str(e.kind), 0) + 1
    return Report(
        models=models,
        totals=Totals(
            models_by_quality={q.value: sum(m.quality == q for m in models) for q in ParseQuality},
            edges=len(edges),
            edges_by_kind=dict(sorted(by_kind.items())),
            model_level_citations=sum(e.model_level_citation for e in edges),
            indirect_edges=len(graph.indirect_edges()),
            indirect_model_level_citations=sum(
                e.model_level_citation for e in graph.indirect_edges()
            ),
            low_confidence_edges=sum(e.confidence == Confidence.LOW for e in edges),
            deferred_indirect=len(
                {(e.from_column, e.to_column) for e in graph.indirect_edges() if e.kind == "WINDOW"}
            ),
            constants=sum(len(m.constants) for m in models),
        ),
    )


# -- coverage summary for artifact ingest (S06) ------------------------------------------------

COVERAGE_LEVELS = ("FULL", "PARTIAL", "TABLE_ONLY", "FAILED")


def gap_category(gap: str) -> str:
    """Group a gap string (``ModelParse.gaps``) by cause, for the coverage summary."""
    if "unexpanded *" in gap:
        return "unexpanded *"
    if "is not a dbt node" in gap:
        return "table not in the manifest"
    if "ephemeral model" in gap:
        return "ephemeral model not unique"
    if "unresolved column" in gap:
        return "unresolved column"
    return "other"


class ModelCoverage(BaseModel):
    model: str
    level: str
    reasons: dict[str, int]
    """Gap category (or the FAILED exception type) -> count."""


class Coverage(BaseModel):
    counts: dict[str, int]
    models: list[ModelCoverage]
    """Every model that is not FULL, worst first."""


def coverage_summary(graph: LineageGraph) -> Coverage:
    """FULL = no gaps; PARTIAL = gaps, but at least one column edge into the model; TABLE_ONLY =
    no column edges (DEPENDS_ON only); FAILED = sqlglot could not parse it. ``ParseQuality``
    itself is unchanged: PARTIAL and TABLE_ONLY here split its TABLE_ONLY."""
    with_edges = {e.to_column.rsplit(".", 1)[0] for e in graph.edges()}
    rows: list[ModelCoverage] = []
    for uid, p in graph.parse_details().items():
        if p.quality == ParseQuality.FULL:
            rows.append(ModelCoverage(model=uid, level="FULL", reasons={}))
            continue
        reasons: dict[str, int] = {}
        if p.quality == ParseQuality.FAILED:
            level = "FAILED"
            cause = (p.reason or "unknown").split(":")[0]
            reasons[cause] = 1
        else:
            level = "PARTIAL" if uid in with_edges else "TABLE_ONLY"
            for gap in p.gaps:
                cat = gap_category(gap)
                reasons[cat] = reasons.get(cat, 0) + 1
        rows.append(ModelCoverage(model=uid, level=level, reasons=dict(sorted(reasons.items()))))
    order = {lvl: i for i, lvl in enumerate(COVERAGE_LEVELS)}
    return Coverage(
        counts={lvl: sum(r.level == lvl for r in rows) for lvl in COVERAGE_LEVELS},
        models=sorted(
            (r for r in rows if r.level != "FULL"), key=lambda r: (-order[r.level], r.model)
        ),
    )
