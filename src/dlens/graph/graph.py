"""The lineage graph: DERIVES edges between columns, plus model-level DEPENDS_ON and CONSUMES."""

import difflib
import json
from pathlib import Path
from typing import Any

import networkx as nx

from dlens import __version__
from dlens.graph.models import (
    AmbiguousColumn,
    ColumnNotFound,
    ImpactResult,
    LineagePath,
    PathList,
)
from dlens.ingest import IngestResult, ingest
from dlens.lineage import (
    DeferredIndirect,
    Edge,
    LineageResult,
    ModelParse,
    ParseQuality,
    column_id,
    extract_lineage,
    short_id,
)

# Cache-format version: bump whenever the JSON shape changes. v2 added ``dlens_version``.
FORMAT_VERSION = 2
DEFAULT_MAX_PATHS = 1000
SUGGESTIONS = 3


class LineageGraph:
    """Column nodes joined by DERIVES edges, in one ``nx.DiGraph``.

    Nodes come from the catalog, so a column with no edges still exists. Each edge carries its
    full :class:`Edge` (kind, expression, file, lines, confidence) under the ``edge`` attribute.
    DEPENDS_ON / CONSUMES are plain sorted pair lists; CONTAINS is the ``model`` node attribute.
    """

    def __init__(
        self,
        columns: dict[str, dict[str, str]],
        edges: list[Edge],
        depends_on: list[tuple[str, str]],
        consumes: list[tuple[str, str]],
        models: dict[str, dict[str, str]],
        exposures: dict[str, dict[str, str]],
        parse: dict[str, ModelParse],
        deferred: list[DeferredIndirect],
    ) -> None:
        self._g: Any = nx.DiGraph()
        for cid in sorted(columns):
            self._g.add_node(cid, **columns[cid])
        for e in sorted(edges, key=lambda e: (e.from_column, e.to_column)):
            self._g.add_edge(e.from_column, e.to_column, edge=e)
        self._depends_on = sorted(set(depends_on))
        self._consumes = sorted(set(consumes))
        self._models = dict(sorted(models.items()))
        self._exposures = dict(sorted(exposures.items()))
        self._parse = {k: v.model_copy(update={"deferred_indirect": []}) for k, v in parse.items()}
        self._deferred = sorted(deferred, key=lambda d: (d.to_column, d.from_column, d.kind))
        self._short_index: dict[str, list[str]] | None = None

    # -- construction ------------------------------------------------------------------------

    @classmethod
    def from_results(cls, ingested: IngestResult, result: LineageResult) -> "LineageGraph":
        """Pure constructor: no dbt, no file access."""
        columns = {
            column_id(t.unique_id, c.name): {"model": t.unique_id, "name": c.name, "type": c.type}
            for t in ingested.catalog.tables
            for c in t.columns
        }
        models = {
            n.unique_id: {
                "resource_type": n.resource_type,
                "name": n.name,
                "file": n.original_file_path or "",
            }
            for n in ingested.manifest.nodes.values()
        }
        exposures = {
            x.unique_id: {"name": x.name, "type": x.type}
            for x in ingested.manifest.exposures.values()
        }
        consumes = [
            (x.unique_id, dep)
            for x in ingested.manifest.exposures.values()
            for dep in x.depends_on.nodes
        ]
        deferred = [d for p in result.parse_report.values() for d in p.deferred_indirect]
        return cls(
            columns=columns,
            edges=result.edges,
            depends_on=result.depends_on,
            consumes=consumes,
            models=models,
            exposures=exposures,
            parse=result.parse_report,
            deferred=deferred,
        )

    # -- inspection --------------------------------------------------------------------------

    @property
    def nx_graph(self) -> Any:
        """The underlying ``nx.DiGraph`` (read it, don't mutate it)."""
        return self._g

    def has_column(self, column: str) -> bool:
        return bool(self._g.has_node(column))

    def columns(self) -> list[str]:
        return sorted(self._g.nodes)

    def edge(self, from_column: str, to_column: str) -> Edge:
        e: Edge = self._g.edges[from_column, to_column]["edge"]
        return e

    def edges(self) -> list[Edge]:
        """Every DERIVES edge, sorted by (from, to)."""
        return [self.edge(u, v) for u, v in sorted(self._g.edges)]

    def depends_on(self) -> list[tuple[str, str]]:
        return list(self._depends_on)

    def consumes(self) -> list[tuple[str, str]]:
        return list(self._consumes)

    def model_of(self, column: str) -> str:
        model: str = self._g.nodes[column]["model"]
        return model

    def parse_report(self) -> dict[str, ParseQuality]:
        return {uid: p.quality for uid, p in sorted(self._parse.items())}

    def parse_details(self) -> dict[str, ModelParse]:
        """Full per-model parse info, with ``deferred_indirect`` reattached to its model."""
        by_model: dict[str, list[DeferredIndirect]] = {}
        for d in self._deferred:
            if self._g.has_node(d.to_column):
                by_model.setdefault(self.model_of(d.to_column), []).append(d)
        return {
            uid: p.model_copy(update={"deferred_indirect": by_model.get(uid, [])})
            for uid, p in sorted(self._parse.items())
        }

    # -- lookup ------------------------------------------------------------------------------

    def _shorts(self) -> dict[str, list[str]]:
        if self._short_index is None:
            index: dict[str, list[str]] = {}
            for cid in sorted(self._g.nodes):
                index.setdefault(short_id(cid), []).append(cid)
            self._short_index = index
        return self._short_index

    def display_name(self, column: str) -> str:
        """``model.column`` unless two columns share it, then the full id."""
        short = short_id(column)
        return short if len(self._shorts().get(short, [])) <= 1 else column

    def resolve(self, text: str) -> str:
        """Full column id, from a full id or any dotted suffix with at least 2 segments."""
        q = text.strip().lower()
        if self._g.has_node(q):
            return q
        if "." in q:
            hits: list[str] = [c for c in sorted(self._g.nodes) if c.endswith("." + q)]
            if len(hits) == 1:
                return hits[0]
            if hits:
                raise AmbiguousColumn(text, hits)
        shorts = self._shorts()
        close = difflib.get_close_matches(q, list(shorts), n=SUGGESTIONS, cutoff=0.0)
        raise ColumnNotFound(text, [self.display_name(shorts[s][0]) for s in close])

    # -- traversal ---------------------------------------------------------------------------

    def _require(self, column: str) -> None:
        if not self._g.has_node(column):
            raise ColumnNotFound(column, [])

    def upstream(
        self,
        column_id: str,
        max_depth: int = 10,
        include_indirect: bool = False,
        max_paths: int = DEFAULT_MAX_PATHS,
    ) -> PathList:
        """Every path from ``column_id`` back to a column with no upstream (or ``max_depth``).

        Stops at ``max_paths`` and sets ``truncated``. ``include_indirect`` is a no-op in v0.1:
        the graph has no indirect edges yet.
        """
        self._require(column_id)
        out = PathList()

        def emit(trail: list[Edge]) -> None:
            if not trail:
                return
            if len(out) >= max_paths:
                out.truncated = True
                return
            out.append(LineagePath(edges=tuple(trail)))

        def walk(col: str, trail: list[Edge]) -> None:
            preds = sorted(self._g.predecessors(col))
            if not preds:
                emit(trail)
                return
            if len(trail) >= max_depth:
                out.depth_limited = True
                emit(trail)
                return
            for p in preds:
                walk(p, [*trail, self.edge(p, col)])
                if out.truncated:
                    return

        walk(column_id, [])
        return out

    def downstream(
        self, column_id: str, max_depth: int = 10, include_indirect: bool = True
    ) -> ImpactResult:
        """Columns that read ``column_id``, by shortest depth, with affected models/exposures.

        ``include_indirect`` is a no-op in v0.1: the graph has no indirect edges yet.
        """
        self._require(column_id)
        seen = {column_id}
        frontier = [column_id]
        by_depth: dict[int, list[str]] = {}
        via: dict[str, Edge] = {}
        for depth in range(1, max_depth + 1):
            nxt: list[str] = []
            for col in frontier:
                for succ in sorted(self._g.successors(col)):
                    if succ not in seen:
                        seen.add(succ)
                        via[succ] = self.edge(col, succ)
                        nxt.append(succ)
            if not nxt:
                frontier = []
                break
            by_depth[depth] = sorted(nxt)
            frontier = nxt
        truncated = any(s not in seen for col in frontier for s in self._g.successors(col))

        root_model = self.model_of(column_id)
        models = sorted({self.model_of(c) for c in via})
        touched = {*models, root_model}
        exposures = sorted({x for x, m in self._consumes if m in touched})
        return ImpactResult(
            root=column_id,
            columns_by_depth=by_depth,
            via=via,
            models=models,
            exposures=exposures,
            truncated=truncated,
        )

    # -- persistence -------------------------------------------------------------------------

    def _to_dict(self) -> dict[str, Any]:
        return {
            "version": FORMAT_VERSION,
            "dlens_version": __version__,
            "nodes": [{"id": c, **self._g.nodes[c]} for c in sorted(self._g.nodes)],
            "derives": [self.edge(u, v).model_dump(mode="json") for u, v in sorted(self._g.edges)],
            "depends_on": [list(p) for p in self._depends_on],
            "consumes": [list(p) for p in self._consumes],
            "models": [{"unique_id": k, **v} for k, v in self._models.items()],
            "exposures": [{"unique_id": k, **v} for k, v in self._exposures.items()],
            "parse_report": {
                k: v.model_dump(mode="json", exclude={"unique_id", "deferred_indirect"})
                for k, v in sorted(self._parse.items())
            },
            "deferred_indirect": [d.model_dump(mode="json") for d in self._deferred],
        }

    def save(self, path: Path) -> None:
        """Write a sorted, diffable JSON edge list."""
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(self._to_dict(), indent=2, sort_keys=True) + "\n")

    @classmethod
    def load(cls, path: Path) -> "LineageGraph":
        raw = json.loads(path.read_text())
        if raw.get("version") != FORMAT_VERSION:
            raise ValueError(f"{path}: unsupported graph version {raw.get('version')!r}")
        if raw.get("dlens_version") != __version__:
            raise ValueError(
                f"{path}: built by dlens {raw.get('dlens_version')!r}, running {__version__!r}"
            )
        return cls(
            columns={n["id"]: {k: v for k, v in n.items() if k != "id"} for n in raw["nodes"]},
            edges=[Edge.model_validate(e) for e in raw["derives"]],
            depends_on=[(a, b) for a, b in raw["depends_on"]],
            consumes=[(a, b) for a, b in raw["consumes"]],
            models={
                m["unique_id"]: {k: v for k, v in m.items() if k != "unique_id"}
                for m in raw["models"]
            },
            exposures={
                x["unique_id"]: {k: v for k, v in x.items() if k != "unique_id"}
                for x in raw["exposures"]
            },
            parse={uid: ModelParse(unique_id=uid, **p) for uid, p in raw["parse_report"].items()},
            deferred=[DeferredIndirect.model_validate(d) for d in raw["deferred_indirect"]],
        )

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, LineageGraph):
            return NotImplemented
        return self._to_dict() == other._to_dict()

    __hash__ = None  # type: ignore[assignment]


def build_graph(project_dir: Path, dialect: str = "duckdb") -> LineageGraph:
    """Run dbt (ingest), extract column lineage and build the graph."""
    ingested = ingest(project_dir)
    return LineageGraph.from_results(ingested, extract_lineage(ingested, project_dir, dialect))
