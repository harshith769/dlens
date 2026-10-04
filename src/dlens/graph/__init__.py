"""Lineage graph: build, query (upstream/downstream), persist (spec §7)."""

from dlens.graph.cache import load_or_build
from dlens.graph.graph import LineageGraph, build_graph
from dlens.graph.models import (
    AmbiguousColumn,
    ColumnNotFound,
    Hop,
    ImpactResult,
    LineagePath,
    PathList,
    hop_label,
)

__all__ = [
    "AmbiguousColumn",
    "ColumnNotFound",
    "Hop",
    "ImpactResult",
    "LineageGraph",
    "LineagePath",
    "PathList",
    "build_graph",
    "hop_label",
    "load_or_build",
]
