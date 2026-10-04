"""Result types and errors of the lineage graph (spec §7)."""

from pydantic import BaseModel, ConfigDict, Field

from dlens.lineage import Edge, IndirectEdge, IndirectKind

Hop = Edge | IndirectEdge
"""One step of a traversal: a DERIVES edge, or (with ``include_indirect``) a DEPENDS_ON_INDIRECT
edge (ADR 0020)."""


def hop_label(hop: Hop) -> str:
    """``"direct"`` for a DERIVES edge, else the indirect type (``"JOIN"``, ``"FILTER"``, ...)."""
    return "direct" if isinstance(hop, Edge) else str(hop.kind)


def hop_rank(hop: Hop) -> int:
    """Order of preference between hops: a direct edge, then the indirect types in enum order."""
    return 0 if isinstance(hop, Edge) else 1 + list(IndirectKind).index(hop.kind)


class LineagePath(BaseModel):
    """A chain of hops. For ``upstream`` it starts at the queried column and walks to a source:
    ``edges[0].to_column`` is the queried column and each hop's ``from_column`` is the next
    hop's ``to_column``. Hops are DERIVES edges, plus indirect edges with ``include_indirect``."""

    model_config = ConfigDict(frozen=True)

    edges: tuple[Hop, ...]

    @property
    def depth(self) -> int:
        return len(self.edges)

    @property
    def start(self) -> str:
        return self.edges[0].to_column

    @property
    def end(self) -> str:
        return self.edges[-1].from_column


class PathList(list[LineagePath]):
    """The result of ``upstream``: a plain list plus two flags saying why it may be incomplete."""

    truncated: bool = False
    """``max_paths`` was reached, so some paths were not enumerated."""
    depth_limited: bool = False
    """At least one path was cut at ``max_depth`` while it still had upstream columns."""


class ImpactResult(BaseModel):
    root: str
    columns_by_depth: dict[int, list[str]] = Field(default_factory=dict)
    """Affected columns by their shortest distance from the root, in hops (DERIVES hops, plus
    indirect hops with ``include_indirect``: every hop counts one)."""
    via: dict[str, Hop] = Field(default_factory=dict)
    """For each affected column, the hop that first reached it (used to draw the tree); at equal
    depth a direct edge is preferred, then the indirect types in ``IndirectKind`` order."""
    models: list[str] = Field(default_factory=list)
    """unique_ids of models that own an affected column (the root's own model is not included
    unless a column in it is also downstream of the root)."""
    exposures: list[str] = Field(default_factory=list)
    """Exposures that CONSUME an affected model or the root's own model."""
    truncated: bool = False
    """The frontier was not empty at ``max_depth``: more columns lie downstream."""

    @property
    def columns(self) -> list[str]:
        return [c for d in sorted(self.columns_by_depth) for c in self.columns_by_depth[d]]


class ColumnNotFound(LookupError):
    def __init__(self, query: str, suggestions: list[str]) -> None:
        self.query = query
        self.suggestions = suggestions
        hint = f" Did you mean: {', '.join(suggestions)}?" if suggestions else ""
        super().__init__(f"no column matches {query!r}.{hint}")


class AmbiguousColumn(LookupError):
    def __init__(self, query: str, candidates: list[str]) -> None:
        self.query = query
        self.candidates = candidates
        super().__init__(
            f"{query!r} matches {len(candidates)} columns; use a longer id: "
            + ", ".join(candidates)
        )
