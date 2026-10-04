"""Column-level lineage for every model in a dbt project (spec §7).

Per model, in DAG order: sqlglot ``lineage(None, compiled_sql, schema)`` gives one tree per
output column. Each root-to-leaf path is one candidate edge. Leaves are tables, mapped to dbt
unique_ids through the relation map. The kind comes from the projections on the path, and
provenance from the model's source .sql.
"""

import re
from collections.abc import Iterator
from dataclasses import dataclass, field
from graphlib import TopologicalSorter
from pathlib import Path

from sqlglot import exp, maybe_parse
from sqlglot.lineage import Node, lineage, to_node
from sqlglot.optimizer import Scope, build_scope, find_all_in_scope, qualify
from sqlglot.schema import Schema, ensure_schema

from dlens.ingest import IngestResult
from dlens.ingest.artifacts import Node as DbtNode
from dlens.ingest.schema import SqlglotSchema, normalize_relation
from dlens.lineage.classify import (
    Position,
    clause_position,
    column_key,
    key_columns,
    path_kind,
    step_kind,
    window_key_columns,
)
from dlens.lineage.models import (
    Confidence,
    DeferredIndirect,
    Edge,
    EdgeKind,
    IndirectEdge,
    IndirectKind,
    LineageResult,
    ModelParse,
    ParseQuality,
    column_id,
)
from dlens.lineage.provenance import Citation, line_map, locate, locate_clause

Span = tuple[int, int]  # [start, end) character offsets in the compiled SQL


@dataclass(frozen=True)
class _Path:
    """One root-to-leaf path through a sqlglot lineage tree."""

    steps: list[exp.Expr]  # projections inside this model, outermost first
    inputs: list[str]  # inputs[i]: the child (column_key form) that steps[i] reads on this path
    leaf: Node
    branch: int | None  # UNION branch index, if the path goes through a UNION
    scope: exp.Expr | None  # the SELECT of the last step (where an unresolved leaf was read)


@dataclass(frozen=True)
class _RawIndirect:
    """One indirect (upstream id, output column) candidate, before suppression (ADR 0020)."""

    upstream: str
    output: str
    kind: IndirectKind
    key: str  # the key column as written in the qualified clause
    clause: str  # the clause SQL, verbatim from the compiled SQL where positions allow
    confidence: Confidence
    span: Span | None  # the clause in the compiled SQL, None if it could not be found


@dataclass
class _ModelLineage:
    """Raw output of one model, before provenance is attached."""

    edges: list[tuple[str, str, list[exp.Expr], list[str], Confidence, int | None]] = field(
        default_factory=list
    )  # (upstream column id, output column, steps, step inputs, confidence, branch)
    gaps: list[str] = field(default_factory=list)
    deferred: list[tuple[str, str]] = field(default_factory=list)  # (upstream id, output col)
    constants: list[str] = field(default_factory=list)  # outputs with no input column at all
    scope: Scope | None = None  # root scope of the qualified SELECT (shared with indirect edges)
    indirect: list[_RawIndirect] = field(default_factory=list)


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
    inputs: list[str],
    branch: int | None,
    scope: exp.Expr | None,
    dropped: list[Node],
) -> Iterator[_Path]:
    """Yield value paths. Children used only in function-attached key positions (window keys,
    aggregate FILTER / ORDER BY) are not value inputs (ADR 0020); those used only as window keys
    are also appended to `dropped` (the v0.1 ``deferred_indirect`` record)."""
    if not node.downstream:
        yield _Path(steps, inputs, node, branch, scope)
        return
    if isinstance(node.source, exp.Union):
        # The UNION node's expression is the first branch's; only the branches are real steps.
        for i, child in enumerate(node.downstream):
            yield from _walk(child, steps, inputs, i if branch is None else branch, scope, dropped)
        return
    keys = key_columns(node.expression)
    window_keys = window_key_columns(node.expression)
    for child in node.downstream:
        name = column_key(child.name)
        if name in window_keys:
            dropped.append(child)
        elif name not in keys:
            yield from _walk(
                child, [*steps, node.expression], [*inputs, name], branch, node.source, dropped
            )


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


def qualified_scope(sql: str, ingest: IngestResult, dialect: str = "duckdb") -> Scope:
    """Parse and qualify a compiled SELECT once, exactly as ``sqlglot.lineage`` would, and build
    its scope tree. Direct and indirect edges both read this one qualified AST."""
    schema = ensure_schema(ingest.schema, dialect=dialect)  # type: ignore[arg-type]
    expression: exp.Expr = qualify.qualify(
        maybe_parse(sql, dialect=dialect),
        dialect=dialect,
        schema=schema,
        validate_qualify_columns=False,
        identify=False,
    )
    scope = build_scope(expression)
    if scope is None:
        raise ValueError("Cannot build lineage, sql must be SELECT")
    return scope


def lineage_for_sql(sql: str, ingest: IngestResult, dialect: str = "duckdb") -> _ModelLineage:
    """Column lineage of one compiled SELECT. Raises if sqlglot cannot parse or qualify it."""
    scope = qualified_scope(sql, ingest, dialect)
    expression = scope.expression
    schema = ensure_schema(ingest.schema, dialect=dialect)  # type: ignore[arg-type]
    # trim_selects=False: sqlglot's trimming re-parents each projection onto a copy of its SELECT,
    # which would break the parent links of the shared AST. Node.source is then the real SELECT.
    trees = lineage(
        None, expression, schema=schema, dialect=dialect, scope=scope, trim_selects=False
    )
    assert isinstance(trees, dict)  # guarded by golden test #0
    out = _ModelLineage(scope=scope)
    for output, root in trees.items():
        if output == "*":
            out.gaps.append("unexpanded * in the outer SELECT")
            continue
        dropped: list[Node] = []
        found = False
        for path in _walk(root, [], [], None, None, dropped):
            ids, gap = _resolve_leaf(path, ingest)
            if gap:
                out.gaps.append(f"{output} <- {gap}")
            for upstream, conf in ids:
                out.edges.append((upstream, output, path.steps, path.inputs, conf, path.branch))
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
    out.indirect = _indirect(sql, scope, trees, ingest, schema, dialect)
    return out


# -- indirect edges (ADR 0020) -------------------------------------------------------------

# Words that start the next clause: the clause text stops before them (at paren depth 0).
_STARTERS = re.compile(
    r"\b(select|from|where|group|having|qualify|order|limit|join|left|right|inner|full|cross"
    r"|union|window|filter|over|with|on|using)\b",
    re.IGNORECASE,
)


def _clause_text(sql: str, clause: exp.Expr, dialect: str) -> tuple[str, Span | None]:
    """The clause as written in the compiled SQL (whitespace collapsed), e.g. ``on o.user_id =
    c.id`` or ``over (partition by k order by d)``, and its span in the compiled SQL.

    Located through the token positions sqlglot keeps on identifiers and literals. When they are
    missing or point elsewhere (USING is expanded by qualify; positional GROUP BY copies the
    projection's tokens), the text falls back to the qualified SQL and the span comes from a
    keyword scan of the owning SELECT (``_keyword_span``), or is None."""
    span: list[exp.Expr] = [clause]
    closes = False  # the clause is a parenthesised suffix: stop at its closing paren
    allowed: set[str] = set()
    if isinstance(clause, exp.Window):
        keyword, closes, allowed = r"over\s*\(", True, {"order"}
        span = [
            *(clause.args.get("partition_by") or []),
            *[clause.args["order"]] * bool(clause.args.get("order")),
        ]
        fallback = clause.sql(dialect=dialect)
    elif isinstance(clause, exp.Where) and isinstance(clause.parent, exp.Filter):
        keyword, closes, fallback = r"filter\s*\(\s*where", True, clause.parent.sql(dialect)
    elif isinstance(clause, exp.Where | exp.Having | exp.Qualify):
        keyword = clause.key
        fallback = clause.sql(dialect=dialect)
    elif isinstance(clause, exp.Order) and isinstance(clause.parent, exp.AggFunc):
        # ORDER BY inside an aggregate: its `this` is the aggregate's argument, not the clause.
        span = list(clause.expressions)
        keys = ", ".join(e.sql(dialect=dialect) for e in clause.expressions)
        keyword, fallback = r"order\s+by", f"ORDER BY {keys}"
    elif isinstance(clause, exp.Group | exp.Order):
        keyword, fallback = rf"{clause.key}\s+by", clause.sql(dialect=dialect)
    else:  # a JOIN's ON condition (USING is expanded to ON by qualify)
        keyword, fallback = r"on|using", f"ON {clause.sql(dialect=dialect)}"
    starts = [n.meta["start"] for c in span for n in c.walk() if "start" in n.meta]
    ends = [n.meta["end"] for c in span for n in c.walk() if "end" in n.meta]
    if not starts:
        return fallback, _keyword_span(sql, clause)
    first, last = min(starts), max(ends)
    found = None
    for m in re.finditer(rf"\b(?:{keyword})", sql[:first], re.IGNORECASE):
        found = m
    if found is None or not _clean_gap(sql, found.end(), first, allowed):
        return fallback, _keyword_span(sql, clause)
    end = _clause_end(sql, found.start(), last, closes, allowed)
    return " ".join(sql[found.start() : end].split()), (found.start(), end)


def _clause_end(
    sql: str, begin: int, last: int, closes: bool, allowed: set[str], lists: bool = False
) -> int:
    """End offset (exclusive, trailing whitespace dropped) of a clause that starts at `begin`
    and whose last known token ends at `last`: the next comma, semicolon, unmatched paren or
    clause starter at the clause's paren depth (or its own closing paren, for `closes`). With
    `lists`, a comma continues the clause (``group by 1, 2`` scanned from its keyword)."""
    depth = sql.count("(", begin, last + 1) - sql.count(")", begin, last + 1)
    i = last + 1
    while i < len(sql):
        ch = sql[i]
        if ch in "'\"":
            j = sql.find(ch, i + 1)
            i = len(sql) if j < 0 else j + 1
            continue
        if ch == "(":
            depth += 1
        elif ch == ")":
            if depth == 0:
                break
            depth -= 1
            if depth == 0 and closes:
                i += 1
                break
        elif depth == 0 and (ch == ";" or (ch == "," and not lists)):
            break
        elif depth == 0 and (i == 0 or not (sql[i - 1].isalnum() or sql[i - 1] == "_")):
            w = _STARTERS.match(sql, i)
            if w and w.group().lower() not in allowed:
                break
        i += 1
    return begin + len(sql[begin:i].rstrip())


def _select_start(sql: str, select: exp.Select) -> int | None:
    """Offset of the ``select`` keyword of a SELECT, found before its first projection token."""
    starts = [n.meta["start"] for p in select.expressions for n in p.walk() if "start" in n.meta]
    if not starts:
        return None
    found = None
    for m in re.finditer(r"\bselect\b", sql[: min(starts)], re.IGNORECASE):
        found = m
    return found.start() if found else None


def _keyword_span(sql: str, clause: exp.Expr) -> Span | None:
    """Span of a row-set clause whose own tokens are missing or copied: scan the owning SELECT at
    its paren depth for the clause keyword. GROUP BY / ORDER BY: the first match. A JOIN's
    condition (USING): the k-th ON / USING, k counting the joins that have a condition."""
    if isinstance(clause, exp.Group | exp.Order) and isinstance(clause.parent, exp.Select):
        select, keyword, nth = clause.parent, rf"{clause.key}\s+by\b", 0
    elif isinstance(clause.parent, exp.Join) and isinstance(clause.parent.parent, exp.Select):
        select, keyword = clause.parent.parent, r"(?:on|using)\b"
        joins = [j for j in select.args.get("joins") or [] if j.args.get("on")]
        nth = next((k for k, j in enumerate(joins) if j is clause.parent), -1)
        if nth < 0:
            return None
    else:
        return None
    i = _select_start(sql, select)
    if i is None:
        return None
    i += len("select")
    depth, seen = 0, 0
    while i < len(sql):
        ch = sql[i]
        if ch in "'\"":
            j = sql.find(ch, i + 1)
            i = len(sql) if j < 0 else j + 1
            continue
        if ch == "(":
            depth += 1
        elif ch == ")":
            depth -= 1
            if depth < 0:
                return None
        elif ch == ";":
            return None
        elif depth == 0 and not (sql[i - 1].isalnum() or sql[i - 1] == "_"):
            m = re.compile(keyword, re.IGNORECASE).match(sql, i)
            if m:
                if seen == nth:
                    closes = m.group().lower() == "using"
                    lists = isinstance(clause, exp.Group | exp.Order)
                    return i, _clause_end(sql, i, m.end() - 1, closes, set(), lists)
                seen += 1
            elif re.compile(r"union\b|except\b|intersect\b", re.IGNORECASE).match(sql, i):
                return None
        i += 1
    return None


def _written_key(sql: str, span: Span | None, clause: exp.Expr, col: exp.Column) -> str | None:
    """The GROUP BY / ORDER BY item as written when it is a position (``group by 1`` ->
    ``"1"``): qualify replaces positions with copies of the projection."""
    if span is None or not isinstance(clause, exp.Group | exp.Order):
        return None
    if isinstance(clause.parent, exp.AggFunc):
        return None
    item: exp.Expr = col
    while item.parent is not None and item.parent is not clause:
        item = item.parent
    if item.parent is not clause or item.arg_key != "expressions":
        return None
    body = re.sub(r"^\w+\s+by\s*", "", sql[span[0] : span[1]], flags=re.IGNORECASE)
    written, depth, start = [], 0, 0
    for i, ch in enumerate(body):
        depth += (ch == "(") - (ch == ")")
        if ch == "," and depth == 0:
            written.append(body[start:i])
            start = i + 1
    written.append(body[start:])
    k = next((k for k, e in enumerate(clause.expressions) if e is item), -1)
    if not 0 <= k < len(written):
        return None
    token = written[k].split()[0] if written[k].split() else ""
    return token if token.isdigit() else None


def _clean_gap(sql: str, start: int, end: int, allowed: set[str]) -> bool:
    """True if nothing between the keyword and the clause's first token belongs to another
    clause: no closing paren below the keyword's level, and no other clause starter at its
    level (``where exists (select ...`` is fine; a keyword in an earlier CTE is not)."""
    depth = 0
    for i in range(start, end):
        ch = sql[i]
        if ch == "(":
            depth += 1
        elif ch == ")":
            depth -= 1
            if depth < 0:
                return False
        elif depth == 0 and (i == 0 or not (sql[i - 1].isalnum() or sql[i - 1] == "_")):
            w = _STARTERS.match(sql, i)
            if w and w.group().lower() not in allowed:
                return False
    return True


def _find_source(scope: Scope, table: str) -> exp.Table | Scope | None:
    """The source a qualified column's table name refers to: this scope, then its parents
    (correlated subqueries read the outer query's tables)."""
    s: Scope | None = scope
    while s is not None:
        if table in s.sources:
            src: exp.Table | Scope = s.sources[table]
            return src
        s = s.parent
    return None


def _through(
    name: str, scope: Scope, ingest: IngestResult, schema: Schema, dialect: str
) -> list[tuple[str, Confidence]]:
    """Upstream columns of `name` in a CTE / derived table / this SELECT's own projection,
    with the same walk and leaf resolution as direct edges (value paths only)."""
    try:
        node = to_node(name, scope, dialect, schema=schema, trim_selects=False)
    except Exception:  # sqlglot could not find the column: no edge rather than a guess
        return []
    found: list[tuple[str, Confidence]] = []
    for path in _walk(node, [], [], None, None, []):
        found += _resolve_leaf(path, ingest)[0]
    return found


def _resolve_key(
    col: exp.Column, scope: Scope, ingest: IngestResult, schema: Schema, dialect: str
) -> list[tuple[str, Confidence]]:
    """Upstream model columns of a key column, resolved like a direct edge's leaf."""
    name = col.name
    if col.table:
        src = _find_source(scope, col.table)
        if isinstance(src, exp.Table):
            uid = ingest.relation_map.get(_table_name(src))
            return [(column_id(uid, name), Confidence.HIGH)] if uid else []
        if isinstance(src, Scope):
            return _through(name, src, ingest, schema, dialect)
        return []
    select = scope.expression
    if isinstance(select, exp.Select) and name in {p.alias_or_name for p in select.selects}:
        return _through(name, scope, ingest, schema, dialect)  # ORDER BY alias / position
    # Unqualified and not an alias: every table in the scope that could hold it, LOW.
    candidates = [_table_name(t) for t in _scope_tables(select)]
    known = [r for r in candidates if _has_column(ingest.schema, r, name.lower())]
    if not known:
        known = [r for r in candidates if _has_column(ingest.schema, r, name.lower()) is None]
    return [
        (column_id(ingest.relation_map[r], name), Confidence.LOW)
        for r in known
        if r in ingest.relation_map
    ]


def _children(scope: Scope) -> list[Scope]:
    return [
        *scope.cte_scopes,
        *scope.derived_table_scopes,
        *scope.subquery_scopes,
        *scope.set_operation_scopes,
        *scope.udtf_scopes,
    ]


def _indirect(
    sql: str,
    root: Scope,
    trees: dict[str, Node],
    ingest: IngestResult,
    schema: Schema,
    dialect: str,
) -> list[_RawIndirect]:
    """Indirect candidates for one model (ADR 0020). Targets come from the lineage trees: a
    row-set clause in SELECT S reaches every output whose tree passes through S; a
    function-attached clause reaches the outputs whose tree passes through its projection."""
    by_select: dict[int, set[str]] = {}
    by_projection: dict[int, set[str]] = {}
    for output, tree in trees.items():
        if output == "*":
            continue
        for node in tree.walk():
            if isinstance(node.source, exp.Select):
                by_select.setdefault(id(node.source), set()).add(output)
            by_projection.setdefault(id(node.expression), set()).add(output)

    out: list[_RawIndirect] = []
    texts: dict[int, tuple[str, Span | None]] = {}

    def emit(
        col: exp.Column,
        scope: Scope,
        kind: IndirectKind,
        clause: exp.Expr,
        to: set[str],
        key: str | None = None,
    ) -> None:
        if not to:
            return
        if id(clause) not in texts:
            texts[id(clause)] = _clause_text(sql, clause, dialect)
        text, span = texts[id(clause)]
        key = key or _written_key(sql, span, clause, col) or col.sql(dialect=dialect)
        for upstream, conf in _resolve_key(col, scope, ingest, schema, dialect):
            out.extend(_RawIndirect(upstream, t, kind, key, text, conf, span) for t in sorted(to))

    def targets(pos: Position, select: exp.Expr) -> set[str]:
        if pos.projection is not None:
            return by_projection.get(id(pos.projection), set())
        return by_select.get(id(select), set())

    seen: set[int] = set()

    def visit(scope: Scope, inherited: tuple[IndirectKind, exp.Expr, set[str]] | None) -> None:
        if id(scope) in seen:
            return
        seen.add(id(scope))
        select = scope.expression
        if isinstance(select, exp.Select):
            for col in find_all_in_scope(select, exp.Column):
                if inherited is not None:
                    emit(col, scope, *inherited)
                elif (pos := clause_position(col, select)) is not None:
                    emit(col, scope, pos.kind, pos.clause, targets(pos, select))
            group = select.args.get("group")
            if inherited is None and group is not None and group.args.get("all"):
                # GROUP BY ALL: the columns of every non-aggregate projection are group keys.
                to = by_select.get(id(select), set())
                for proj in select.selects:
                    if step_kind(proj) != EdgeKind.AGGREGATION:
                        for col in proj.find_all(exp.Column):
                            emit(col, scope, IndirectKind.GROUP_BY, group, to, "ALL")
        for child in _children(scope):
            if inherited is not None or not isinstance(select, exp.Select):
                visit(child, inherited)
            elif child in scope.subquery_scopes and (
                pos := clause_position(child.expression, select)
            ):
                # A subquery inside a clause (IN, EXISTS, a comparison): every column in it
                # takes the clause's type and targets (ADR 0020).
                visit(child, (pos.kind, pos.clause, targets(pos, select)))
            else:
                visit(child, None)  # CTE, derived table, UNION branch, SELECT-list subquery

    visit(root, None)
    return out


def _model_edges(
    model: DbtNode, raw: _ModelLineage, source: str | None, dialect: str
) -> list[Edge]:
    """Classify and cite each path, then keep one edge per (from, to): the strongest kind."""
    best: dict[tuple[str, str], Edge] = {}
    file = model.original_file_path or ""
    for upstream, output, steps, inputs, conf, branch in raw.edges:
        kind = path_kind(steps, inputs, upstream.split(".")[-1], output)
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


def _model_indirect(
    model: DbtNode, raw: _ModelLineage, source: str | None, direct: set[tuple[str, str]]
) -> tuple[list[IndirectEdge], list[str]]:
    """One edge per (from, to, kind), HIGH over LOW; pairs with a direct edge are dropped (D7).
    Each edge cites its clause's lines in the source file (``locate_clause``). A clause that
    can't be located cites the whole file, and its reason is returned (``citation_gaps``)."""
    whole = (
        (1, max(1, source.count("\n") + (0 if source.endswith("\n") else 1))) if source else (1, 1)
    )
    compiled = model.compiled_code or ""
    lines_of = line_map(source, compiled) if source is not None else None
    best: dict[tuple[str, str, IndirectKind], IndirectEdge] = {}
    gaps: list[str] = []
    for r in raw.indirect:
        to = column_id(model.unique_id, r.output)
        if (r.upstream, to) in direct:
            continue
        if source is None:
            cite: Citation | str = "source file not found"
        else:
            cite = locate_clause(source, compiled, r.span, r.key, lines_of)
        if isinstance(cite, str) and (gap := f"{r.kind} {r.clause}: {cite}") not in gaps:
            gaps.append(gap)
        edge = IndirectEdge(
            from_column=r.upstream,
            to_column=to,
            kind=r.kind,
            key=r.key,
            expression=r.clause,
            file=model.original_file_path or "",
            lines=whole if isinstance(cite, str) else cite.lines,
            model_level_citation=isinstance(cite, str),
            confidence=r.confidence,
        )
        k = (edge.from_column, edge.to_column, edge.kind)
        old = best.get(k)
        if old is None or (old.confidence == Confidence.LOW and r.confidence == Confidence.HIGH):
            best[k] = edge
    return sorted(best.values(), key=lambda e: (e.to_column, e.from_column, e.kind)), gaps


def extract_lineage(
    ingest: IngestResult, project_dir: Path, dialect: str = "duckdb"
) -> LineageResult:
    """Direct column edges, manifest DEPENDS_ON edges and a parse report for every model."""
    edges: list[Edge] = []
    indirect: list[IndirectEdge] = []
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
        model_indirect, citation_gaps = _model_indirect(model, raw, source, direct)
        indirect += model_indirect
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
            citation_gaps=citation_gaps,
        )
    return LineageResult(edges=edges, depends_on=depends_on, parse_report=report, indirect=indirect)
