"""Edge-kind classification (DESIGN.md "Conventions").

Each non-leaf node on a sqlglot lineage path is one *step*: a projection inside this model
(a CTE column, then the outer SELECT). A step is either a bare column (pass-through) or an
operation on the input the path reads. The edge kind is the strongest operation on the path; a
path of pure pass-throughs is IDENTITY or RENAME depending on whether the name changed end to end.
"""

from dataclasses import dataclass

from sqlglot import exp

from dlens.lineage.models import EdgeKind, IndirectKind


def _unwrap(expr: exp.Expr) -> exp.Expr:
    return expr.this if isinstance(expr, exp.Alias) else expr


# Wrappers between a windowed aggregate and its Window: ``count(x) FILTER (WHERE c) OVER (...)``.
_AGG_WRAPPERS = (exp.Filter, exp.IgnoreNulls, exp.RespectNulls)


def _windowed(agg: exp.Expr) -> bool:
    """Is this aggregate the function of a window (``sum(x) OVER (...)``)? Only then does it keep
    the row grain. The inner ``sum`` of ``sum(sum(x)) OVER (...)`` is a grouped aggregate."""
    node = agg
    while isinstance(node.parent, _AGG_WRAPPERS) and node.arg_key == "this":
        node = node.parent
    return isinstance(node.parent, exp.Window) and node.arg_key == "this"


def _in_subquery(node: exp.Expr, root: exp.Expr) -> bool:
    """Is `node` inside a subquery below `root`? A subquery is its own lineage step."""
    while node is not root and node.parent is not None:
        node = node.parent
        if node is not root and isinstance(node, exp.Subquery | exp.Select):
            return True
    return False


def _occurrence_kind(col: exp.Expr, root: exp.Expr) -> EdgeKind:
    """Kind of one column occurrence: AGGREGATION if a grouped aggregate encloses it."""
    node = col
    while node is not root and node.parent is not None:
        node = node.parent
        if isinstance(node, exp.AggFunc) and not _windowed(node):
            return EdgeKind.AGGREGATION
    return EdgeKind.TRANSFORMATION


def step_kind(expr: exp.Expr, input_column: str | None = None) -> EdgeKind | None:
    """Kind of one step for one input, or None for a bare column (pass-through).

    The kind is the strongest operation on the input's OWN path through the expression: an
    aggregate in a sibling subtree (``date_diff(d, (SELECT max(x) ...))``) does not raise ``d``.
    `input_column` is the lineage child's name (``column_key`` form); its occurrences inside a
    subquery or in a function-attached key position are not on its path. With no input, or no
    occurrence (the child is a subquery or a star), any grouped aggregate outside a subquery
    decides. An aggregate that is a window's function (``sum(x) over (...)``) keeps the row
    grain, so it is a TRANSFORMATION, like any other non-aggregate expression.
    """
    inner = _unwrap(expr)
    if isinstance(inner, exp.Column):
        return None
    if input_column is not None:
        kinds = [
            _occurrence_kind(col, inner)
            for col in inner.find_all(exp.Column)
            if column_key(col.sql()) == input_column
            and not _in_subquery(col, inner)
            and function_key(col, inner) is None
        ]
        if kinds:
            return max(kinds, key=lambda k: k.rank)
    if any(
        not _windowed(agg) and not _in_subquery(agg, inner) for agg in inner.find_all(exp.AggFunc)
    ):
        return EdgeKind.AGGREGATION
    return EdgeKind.TRANSFORMATION


def path_kind(
    steps: list[exp.Expr], inputs: list[str], leaf_column: str, output_column: str
) -> EdgeKind:
    """Strongest kind over the steps, each judged for the input it passes to (``inputs[i]`` is
    the child read by ``steps[i]``); pure pass-through is IDENTITY or RENAME by name."""
    kinds = [k for k in map(step_kind, steps, inputs) if k is not None]
    if kinds:
        return max(kinds, key=lambda k: k.rank)
    if leaf_column.lower() == output_column.lower():
        return EdgeKind.IDENTITY
    return EdgeKind.RENAME


def column_key(name: str) -> str:
    """Normal form of a lineage node name / column reference: ``table.col``, unquoted, lower."""
    return name.replace('"', "").lower()


def function_key(node: exp.Expr, root: exp.Expr) -> tuple[IndirectKind, exp.Expr] | None:
    """Innermost function-attached key position of `node` below `root` (ADR 0020): the kind and
    the clause node (the Window, the aggregate's FILTER ``Where``, or the aggregate's ``Order``).

    Window PARTITION BY / ORDER BY -> WINDOW; an aggregate's ``FILTER (WHERE ...)`` ->
    CONDITIONAL; ``ORDER BY`` inside an aggregate (``string_agg(x, ',' ORDER BY y)``) -> SORT.
    Function arguments (including CASE conditions) are not key positions.
    """
    while node is not root and node.parent is not None:
        parent = node.parent
        if isinstance(parent, exp.Window) and node.arg_key in ("partition_by", "order"):
            return IndirectKind.WINDOW, parent
        if isinstance(parent, exp.Filter) and node.arg_key == "expression":
            return IndirectKind.CONDITIONAL, node
        if (
            isinstance(parent, exp.Order)
            and node.arg_key == "expressions"
            and isinstance(parent.parent, exp.AggFunc)
        ):
            return IndirectKind.SORT, parent
        node = parent
    return None


def function_key_kind(node: exp.Expr, root: exp.Expr) -> IndirectKind | None:
    found = function_key(node, root)
    return found[0] if found else None


# Row-set clauses of a SELECT (ADR 0020): the clause decides first.
_ROW_SET = {
    "joins": IndirectKind.JOIN,
    "where": IndirectKind.FILTER,
    "having": IndirectKind.FILTER,
    "qualify": IndirectKind.FILTER,
    "group": IndirectKind.GROUP_BY,
    "order": IndirectKind.SORT,
}


@dataclass(frozen=True)
class Position:
    """Where a key column (or a subquery) sits in a SELECT."""

    kind: IndirectKind
    clause: exp.Expr  # Where / Having / Qualify / Group / Order / the JOIN's ON, or Window etc.
    projection: exp.Expr | None  # the SELECT-list item, for function-attached clauses


def clause_position(node: exp.Expr, select: exp.Select) -> Position | None:
    """Indirect position of `node` in `select`, or None (a value: projection argument, CASE
    condition, FROM). The outermost clause of the SELECT wins: a window key inside QUALIFY is
    FILTER. In the SELECT list, the innermost function-attached key position decides."""
    child = node
    while child.parent is not None and child.parent is not select:
        child = child.parent
    if child.parent is None:
        return None
    key = child.arg_key
    if key == "expressions":
        found = function_key(node, child)
        return Position(found[0], found[1], child) if found else None
    kind = _ROW_SET.get(key or "")
    if kind is None:
        return None
    if kind == IndirectKind.JOIN:
        on = child.args.get("on")
        if on is None or not (node is on or _contains(on, node)):
            return None  # e.g. the joined table itself
        return Position(kind, on, None)
    return Position(kind, child, None)


def _contains(root: exp.Expr, node: exp.Expr) -> bool:
    while node.parent is not None:
        if node.parent is root:
            return True
        node = node.parent
    return False


def key_columns(expr: exp.Expr) -> dict[str, set[IndirectKind]]:
    """Columns referenced *only* in function-attached key positions within this step, with the
    kinds of those positions.

    sqlglot's lineage returns them as children, but they are not direct edges (ADR 0020): window
    keys are WINDOW, aggregate ``FILTER (WHERE)`` columns CONDITIONAL, aggregate ``ORDER BY``
    columns SORT. A column that is also read as a value stays a direct input.
    """
    value: set[str] = set()
    keys: dict[str, set[IndirectKind]] = {}
    for col in expr.find_all(exp.Column):
        key = column_key(col.sql())
        kind = function_key_kind(col, expr)
        if kind is None:
            value.add(key)
        else:
            keys.setdefault(key, set()).add(kind)
    return {k: v for k, v in keys.items() if k not in value}
