"""Edge-kind classification (DESIGN.md "Conventions").

Each non-leaf node on a sqlglot lineage path is one *step*: a projection inside this model
(a CTE column, then the outer SELECT). A step is either a bare column (pass-through) or an
operation. The edge kind is the strongest operation on the path; a path of pure
pass-throughs is IDENTITY or RENAME depending on whether the name changed end to end.
"""

from sqlglot import exp

from dlens.lineage.models import EdgeKind


def _unwrap(expr: exp.Expr) -> exp.Expr:
    return expr.this if isinstance(expr, exp.Alias) else expr


def _under(node: exp.Expr, root: exp.Expr, window_spec_only: bool) -> bool:
    """Is `node` inside a Window below `root`? With `window_spec_only`, only inside its
    PARTITION BY / ORDER BY (not its function argument)."""
    while node is not root and node.parent is not None:
        parent = node.parent
        if isinstance(parent, exp.Window):
            if not window_spec_only or node.arg_key in ("partition_by", "order"):
                return True
        node = parent
    return False


def step_kind(expr: exp.Expr) -> EdgeKind | None:
    """Kind of one step, or None for a bare column (pass-through).

    An aggregate inside a window (``sum(x) over (...)``) keeps the row grain, so it is a
    TRANSFORMATION, like any other non-aggregate expression.
    """
    inner = _unwrap(expr)
    if isinstance(inner, exp.Column):
        return None
    if any(not _under(agg, inner, False) for agg in inner.find_all(exp.AggFunc)):
        return EdgeKind.AGGREGATION
    return EdgeKind.TRANSFORMATION


def path_kind(steps: list[exp.Expr], leaf_column: str, output_column: str) -> EdgeKind:
    """Strongest kind over the steps; pure pass-through is IDENTITY or RENAME by name."""
    kinds = [k for k in map(step_kind, steps) if k is not None]
    if kinds:
        return max(kinds, key=lambda k: k.rank)
    if leaf_column.lower() == output_column.lower():
        return EdgeKind.IDENTITY
    return EdgeKind.RENAME


def column_key(name: str) -> str:
    """Normal form of a lineage node name / column reference: ``table.col``, unquoted, lower."""
    return name.replace('"', "").lower()


def window_key_columns(expr: exp.Expr) -> set[str]:
    """Columns referenced *only* in a window's PARTITION BY / ORDER BY within this step.

    sqlglot's lineage returns them as children, but DESIGN.md says they are not direct edges
    (they are indirect WINDOW dependencies, phase v0.3).
    """
    value: set[str] = set()
    keys: set[str] = set()
    for col in expr.find_all(exp.Column):
        key = column_key(col.sql())
        (keys if _under(col, expr, True) else value).add(key)
    return keys - value
