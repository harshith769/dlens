"""Data types produced by the lineage engine (spec §6 graph schema)."""

from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class EdgeKind(StrEnum):
    """Direct-edge kinds, weakest first (DESIGN.md strongest-kind rule)."""

    IDENTITY = "IDENTITY"
    RENAME = "RENAME"
    TRANSFORMATION = "TRANSFORMATION"
    AGGREGATION = "AGGREGATION"

    @property
    def rank(self) -> int:
        return list(EdgeKind).index(self)


class Confidence(StrEnum):
    HIGH = "high"
    LOW = "low"


class ParseQuality(StrEnum):
    FULL = "FULL"
    TABLE_ONLY = "TABLE_ONLY"
    FAILED = "FAILED"


class _Frozen(BaseModel):
    model_config = ConfigDict(frozen=True)


class Edge(_Frozen):
    """A DERIVES edge: the value of `from_column` flows into `to_column`."""

    from_column: str
    to_column: str
    kind: EdgeKind
    expression: str
    file: str
    lines: tuple[int, int]
    model_level_citation: bool = False
    confidence: Confidence = Confidence.HIGH


class DeferredIndirect(_Frozen):
    """A column used only as a key (e.g. window PARTITION BY / ORDER BY). Not an edge in v0.1;
    kept so v0.3 can turn it into a DEPENDS_ON_INDIRECT edge without re-deriving it."""

    from_column: str
    to_column: str
    kind: Literal["WINDOW"]


class ModelParse(BaseModel):
    unique_id: str
    quality: ParseQuality
    reason: str | None = None
    gaps: list[str] = Field(default_factory=list)
    constants: list[str] = Field(default_factory=list)
    """Output columns that read no input column (literals, ``current_timestamp``). Not gaps."""
    deferred_indirect: list[DeferredIndirect] = Field(default_factory=list)


class LineageResult(BaseModel):
    edges: list[Edge]
    depends_on: list[tuple[str, str]]
    """(model, upstream node) pairs from the manifest; complete even when parsing fails."""
    parse_report: dict[str, ModelParse]


def column_id(unique_id: str, column: str) -> str:
    """Spec §6 id, e.g. ``model.shop.stg_orders.order_id`` or ``seed.shop.raw_orders.id``."""
    return f"{unique_id}.{column}".lower()


def short_id(col_id: str) -> str:
    """``model.shop.stg_orders.order_id`` -> ``stg_orders.order_id`` (gold-spec form).

    For comparison only: two packages or sources with the same table name collide here.
    """
    return ".".join(col_id.split(".")[-2:])
