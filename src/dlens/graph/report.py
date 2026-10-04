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
            deferred_indirect=sum(len(p.deferred_indirect) for p in graph.parse_details().values()),
            constants=sum(len(m.constants) for m in models),
        ),
    )
