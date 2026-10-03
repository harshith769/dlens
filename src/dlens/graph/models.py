"""Result types and errors of the lineage graph (spec §7)."""

from pydantic import BaseModel, ConfigDict, Field

from dlens.lineage import Edge


class LineagePath(BaseModel):
    """A chain of DERIVES edges. For ``upstream`` it starts at the queried column and walks to a
    source: ``edges[0].to_column`` is the queried column and each edge's ``from_column`` is the
    next edge's ``to_column``."""

    model_config = ConfigDict(frozen=True)

    edges: tuple[Edge, ...]

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
    """Affected columns by their shortest distance (in DERIVES hops) from the root."""
    via: dict[str, Edge] = Field(default_factory=dict)
    """For each affected column, the edge that first reached it (used to draw the tree)."""
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
