"""Column-level lineage for every model in a dbt project (spec §7).

Per model, in DAG order: sqlglot ``lineage(None, compiled_sql, schema)`` gives one tree per
output column. Each root-to-leaf path is one candidate edge. Leaves are tables, mapped to dbt
unique_ids through the relation map. The kind comes from the projections on the path, and
provenance from the model's source .sql.
"""

from collections.abc import Iterator
from dataclasses import dataclass, field
from graphlib import TopologicalSorter
from pathlib import Path

from sqlglot import exp
from sqlglot.lineage import Node, lineage

from dlens.ingest import IngestResult
from dlens.ingest.artifacts import Node as DbtNode
from dlens.ingest.schema import SqlglotSchema, normalize_relation
from dlens.lineage.classify import column_key, path_kind, window_key_columns
from dlens.lineage.models import (
    Confidence,
    DeferredIndirect,
    Edge,
    LineageResult,
    ModelParse,
    ParseQuality,
    column_id,
)
from dlens.lineage.provenance import locate


@dataclass(frozen=True)
class _Path:
    """One root-to-leaf path through a sqlglot lineage tree."""

    steps: list[exp.Expr]  # projections inside this model, outermost first
    leaf: Node
    branch: int | None  # UNION branch index, if the path goes through a UNION
    scope: exp.Expr | None  # the SELECT of the last step (where an unresolved leaf was read)


@dataclass
class _ModelLineage:
    """Raw output of one model, before provenance is attached."""

    edges: list[tuple[str, str, list[exp.Expr], Confidence, int | None]] = field(
        default_factory=list
    )  # (upstream column id, output column, steps, confidence, branch)
    gaps: list[str] = field(default_factory=list)
    deferred: list[tuple[str, str]] = field(default_factory=list)  # (upstream id, output col)
    constants: list[str] = field(default_factory=list)  # outputs with no input column at all


def topological_models(ingest: IngestResult) -> list[DbtNode]:
    """Models ordered so every model comes after the models it depends on."""
    models = {m.unique_id: m for m in ingest.manifest.models}
    sorter: TopologicalSorter[str] = TopologicalSorter()
    for uid, m in sorted(models.items()):
        sorter.add(uid, *(d for d in m.depends_on.nodes if d in models))
    return [models[uid] for uid in sorter.static_order()]


def _leaves(node: Node) -> Iterator[Node]:
    if not node.downstream:
        yield node
    for child in node.downstream:
        yield from _leaves(child)


def _walk(
    node: Node,
    steps: list[exp.Expr],
    branch: int | None,
    scope: exp.Expr | None,
    dropped: list[Node],
) -> Iterator[_Path]:
    """Yield value paths; children used only as window keys are appended to `dropped`."""
    if not node.downstream:
        yield _Path(steps, node, branch, scope)
        return
    if isinstance(node.source, exp.Union):
        # The UNION node's expression is the first branch's; only the branches are real steps.
        for i, child in enumerate(node.downstream):
            yield from _walk(child, steps, i if branch is None else branch, scope, dropped)
        return
    keys = window_key_columns(node.expression)
    for child in node.downstream:
        if column_key(child.name) in keys:
            dropped.append(child)
        else:
            yield from _walk(child, [*steps, node.expression], branch, node.source, dropped)


def _table_name(table: exp.Table) -> str:
    return normalize_relation(".".join(p for p in (table.catalog, table.db, table.name) if p))


def _scope_tables(select: exp.Expr) -> list[exp.Table]:
    """Tables directly in a SELECT's FROM and JOINs (not subqueries or CTE bodies)."""
    if not isinstance(select, exp.Select):
        return []
    sources = [select.args["from_"].this] if select.args.get("from_") else []
    sources += [j.this for j in select.args.get("joins") or []]
    return [s for s in sources if isinstance(s, exp.Table)]


def _has_column(schema: SqlglotSchema, relation: str, column: str) -> bool | None:
    """True/False if the relation is in the schema, None if the schema doesn't know it."""
    parts = relation.split(".")
    if len(parts) != 3:
        return None
    table = schema.get(parts[0], {}).get(parts[1], {}).get(parts[2])
    return None if table is None else column.lower() in table


def _is_constant(leaf: Node) -> bool:
    """A leaf projection that reads no column (``'usd' AS currency``, ``current_timestamp``)."""
    expr = leaf.expression
    return not isinstance(expr, exp.Table | exp.Placeholder) and expr.find(exp.Column) is None


def _resolve_leaf(
    path: _Path, ingest: IngestResult
) -> tuple[list[tuple[str, Confidence]], str | None]:
    """Upstream column ids for a leaf, or a gap description. Constants give neither."""
    leaf = path.leaf
    if _is_constant(leaf):
        return [], None
    col = leaf.name.split(".")[-1].replace('"', "").lower()
    if isinstance(leaf.expression, exp.Table):
        rel = _table_name(leaf.expression)
        uid = ingest.relation_map.get(rel)
        if uid is None:
            return [], f"{col}: table {rel} is not a dbt node"
        if col == "*":
            return [], f"unexpanded * from {rel}"
        return [(column_id(uid, col), Confidence.HIGH)], None
    # Placeholder: sqlglot could not tell which table the column belongs to. Emit a
    # low-confidence edge to every table in the step's scope that could hold it.
    candidates = [_table_name(t) for t in _scope_tables(path.scope)] if path.scope else []
    known = [r for r in candidates if _has_column(ingest.schema, r, col)]
    if not known:
        known = [r for r in candidates if _has_column(ingest.schema, r, col) is None]
    ids = [column_id(ingest.relation_map[r], col) for r in known if r in ingest.relation_map]
    if not ids:
        return [], f"{col}: unresolved column (no candidate table)"
    return [(i, Confidence.LOW) for i in ids], None


def lineage_for_sql(sql: str, ingest: IngestResult, dialect: str = "duckdb") -> _ModelLineage:
    """Column lineage of one compiled SELECT. Raises if sqlglot cannot parse or qualify it."""
    trees = lineage(None, sql, schema=ingest.schema, dialect=dialect)
    assert isinstance(trees, dict)  # guarded by golden test #0
    out = _ModelLineage()
    for output, root in trees.items():
        if output == "*":
            out.gaps.append("unexpanded * in the outer SELECT")
            continue
        dropped: list[Node] = []
        found = False
        for path in _walk(root, [], None, None, dropped):
            ids, gap = _resolve_leaf(path, ingest)
            if gap:
                out.gaps.append(f"{output} <- {gap}")
            for upstream, conf in ids:
                out.edges.append((upstream, output, path.steps, conf, path.branch))
                found = True
        for key_node in dropped:
            for leaf in _leaves(key_node):
                if isinstance(leaf.expression, exp.Table):
                    uid = ingest.relation_map.get(_table_name(leaf.expression))
                    if uid:
                        out.deferred.append((column_id(uid, leaf.name.split(".")[-1]), output))
        if not found and not any(g.startswith(f"{output} <-") for g in out.gaps):
            # Every path ended in a constant: recorded, not a gap (the column is fully parsed).
            out.constants.append(output)
    return out


def _model_edges(
    model: DbtNode, raw: _ModelLineage, source: str | None, dialect: str
) -> list[Edge]:
    """Classify and cite each path, then keep one edge per (from, to): the strongest kind."""
    best: dict[tuple[str, str], Edge] = {}
    file = model.original_file_path or ""
    for upstream, output, steps, conf, branch in raw.edges:
        kind = path_kind(steps, upstream.split(".")[-1], output)
        if source is None:
            lines, model_level = (1, 1), True
        else:
            cite = locate(source, output, branch)
            lines, model_level = cite.lines, cite.model_level
        edge = Edge(
            from_column=upstream,
            to_column=column_id(model.unique_id, output),
            kind=kind,
            expression=" <- ".join(s.sql(dialect=dialect) for s in steps),
            file=file,
            lines=lines,
            model_level_citation=model_level,
            confidence=conf,
        )
        key = (edge.from_column, edge.to_column)
        old = best.get(key)
        if old is None or (edge.kind.rank, edge.confidence == Confidence.HIGH) > (
            old.kind.rank,
            old.confidence == Confidence.HIGH,
        ):
            best[key] = edge
    return list(best.values())


def extract_lineage(
    ingest: IngestResult, project_dir: Path, dialect: str = "duckdb"
) -> LineageResult:
    """Direct column edges, manifest DEPENDS_ON edges and a parse report for every model."""
    edges: list[Edge] = []
    report: dict[str, ModelParse] = {}
    depends_on: list[tuple[str, str]] = []
    for model in topological_models(ingest):
        depends_on += [(model.unique_id, d) for d in model.depends_on.nodes]
        if not model.compiled_code:
            report[model.unique_id] = ModelParse(
                unique_id=model.unique_id, quality=ParseQuality.FAILED, reason="no compiled SQL"
            )
            continue
        try:
            raw = lineage_for_sql(model.compiled_code, ingest, dialect)
        except Exception as e:  # any sqlglot failure: keep the model, record why
            report[model.unique_id] = ModelParse(
                unique_id=model.unique_id,
                quality=ParseQuality.FAILED,
                reason=f"{type(e).__name__}: {e}"[:500],
            )
            continue
        src_path = project_dir / (model.original_file_path or "")
        source = src_path.read_text() if src_path.is_file() else None
        edges += _model_edges(model, raw, source, dialect)
        direct = {(e.from_column, e.to_column) for e in edges}
        deferred = sorted(
            {
                DeferredIndirect(from_column=up, to_column=to, kind="WINDOW")
                for up, out in raw.deferred
                if (up, to := column_id(model.unique_id, out)) not in direct
            },
            key=lambda d: (d.to_column, d.from_column),
        )
        report[model.unique_id] = ModelParse(
            unique_id=model.unique_id,
            quality=ParseQuality.TABLE_ONLY if raw.gaps else ParseQuality.FULL,
            reason="; ".join(raw.gaps) if raw.gaps else None,
            gaps=raw.gaps,
            constants=sorted({c.lower() for c in raw.constants}),
            deferred_indirect=deferred,
        )
    return LineageResult(edges=edges, depends_on=depends_on, parse_report=report)
