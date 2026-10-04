"""Gold-spec indirect edges: the D7 expansion from spec rows to (from, to, type) pairs.

A gold spec (``corpora/<corpus>/lineage_spec*.yml``) stores indirect edges compactly, one row per
key column and clause::

    {from: stg_products.product_id, model: int_order_items_enriched, type: JOIN,
     phase: v0.3, targets: all}

``expand_indirect`` turns those rows into column pairs under DESIGN_v2 §10 D7. This is the only
implementation of D7: the spec checker (``scripts/check_gold_spec.py``) and any engine-vs-gold
comparison import it. It reads no files, so it needs no YAML dependency.
"""

from collections.abc import Collection, Iterable, Mapping, Sequence
from dataclasses import dataclass, field

INDIRECT_TYPES = ("JOIN", "FILTER", "GROUP_BY", "WINDOW", "SORT", "CONDITIONAL")
ALL_TARGETS = "all"


@dataclass(frozen=True)
class IndirectPair:
    from_column: str  # short id, e.g. stg_products.product_id
    to_column: str  # short id, e.g. int_order_items_enriched.product_category
    type: str  # one of INDIRECT_TYPES
    via: str | None = None  # CTE / derived-table name or "subquery", when the row names one


@dataclass(frozen=True)
class Expansion:
    pairs: list[IndirectPair]
    # (from, to, type) dropped from a `targets: all` row because a direct edge already holds the
    # pair (D7 "no double counting": only the direct edge is kept).
    suppressed: list[tuple[str, str, str]] = field(default_factory=list)
    # (from, to, type) named in an explicit target list although a direct edge holds the pair.
    # Also dropped from `pairs`; the spec checker fails on any of these.
    conflicts: list[tuple[str, str, str]] = field(default_factory=list)


def expand_indirect(
    rows: Iterable[Mapping[str, object]],
    model_columns: Mapping[str, Sequence[str]],
    direct_pairs: Collection[tuple[str, str]],
) -> Expansion:
    """Expand indirect spec rows into (from, to, type) pairs (DESIGN_v2 §10 D7).

    ``targets: all`` means every column of ``model`` (the clause sits in the final SELECT), minus
    columns that already get a direct edge from the same ``from``. An explicit target list is taken
    as written; a target that already has a direct edge from ``from`` is a conflict. Pairs come out
    in row order, then target order. Raises ValueError on an unknown model, target or type.
    """
    pairs: list[IndirectPair] = []
    suppressed: list[tuple[str, str, str]] = []
    conflicts: list[tuple[str, str, str]] = []
    for row in rows:
        src, model, kind = str(row["from"]), str(row["model"]), str(row["type"])
        via = row.get("via")
        if kind not in INDIRECT_TYPES:
            raise ValueError(f"unknown indirect type {kind!r} in row from {src}")
        if model not in model_columns:
            raise ValueError(f"unknown model {model!r} in row from {src}")
        columns = model_columns[model]
        targets = row["targets"]
        explicit = targets != ALL_TARGETS
        if not explicit:
            names = list(columns)
        elif isinstance(targets, list | tuple) and targets:
            names = [str(t) for t in targets]
            unknown = [t for t in names if t not in columns]
            if unknown:
                raise ValueError(f"unknown targets {unknown} in {model} (row from {src})")
        else:
            raise ValueError(f"targets must be 'all' or a non-empty list (row {src} -> {model})")
        for name in names:
            dst = f"{model}.{name}"
            key = (src, dst, kind)
            if (src, dst) in direct_pairs:
                (conflicts if explicit else suppressed).append(key)
                continue
            pairs.append(IndirectPair(src, dst, kind, str(via) if via is not None else None))
    return Expansion(pairs, suppressed, conflicts)
