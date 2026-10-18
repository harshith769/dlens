"""Gold-spec indirect edges: the D7 expansion from spec rows to (from, to, type) pairs.

A gold spec (``corpora/<corpus>/lineage_spec*.yml``) stores indirect edges compactly, one row per
key column and clause::

    {from: stg_products.product_id, model: int_order_items_enriched, type: JOIN,
     phase: v0.3, targets: all}

``expand_indirect`` turns those rows into column pairs under DESIGN_v2 §10 D7. This is the only
implementation of D7: the spec checker (``scripts/check_gold_spec.py``) and any engine-vs-gold
comparison import it.

The rest of the module computes gold answers from a loaded spec (``build_view``): depths, upstream
and downstream closures (direct-only, or direct + indirect), one-hop inputs, longest paths,
reachability and exposures. The spec checker and the question generator (S09) share these, so a
question's gold and the checker's numbers come from one implementation. It reads no files (callers
pass parsed YAML or file text), so it needs no YAML dependency.
"""

import re
from collections import defaultdict, deque
from collections.abc import Collection, Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any

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


# ----------------------------------------------------------------------------- loaded spec view
def is_column_id(value: object) -> bool:
    """True for a ``model.column`` string (exactly one dot, both parts non-empty)."""
    return isinstance(value, str) and len(value.split(".")) == 2 and all(value.split("."))


def rows(spec: Mapping[str, Any], key: str) -> list[Mapping[str, Any]]:
    """The mapping rows under ``key`` (``edges`` / ``indirect_edges``); anything else is skipped."""
    found = spec.get(key) or []
    return [r for r in found if isinstance(r, Mapping)] if isinstance(found, list) else []


@dataclass
class View:
    """A spec with derived lookups. Inventory-less specs (v1) derive columns from edge endpoints."""

    raw: Mapping[str, Any]
    has_inventory: bool
    seeds: dict[str, list[str]]
    models: dict[str, list[str]]
    depends_on: dict[str, list[str]]
    direct: list[Mapping[str, Any]]
    indirect_rows: list[Mapping[str, Any]]
    pairs: list[IndirectPair] = field(default_factory=list)
    suppressed: list[tuple[str, str, str]] = field(default_factory=list)
    conflicts: list[tuple[str, str, str]] = field(default_factory=list)
    expand_errors: list[str] = field(default_factory=list)

    @property
    def seed_columns(self) -> set[str]:
        return {f"{s}.{c}" for s, cs in self.seeds.items() for c in cs}

    @property
    def model_columns(self) -> set[str]:
        return {f"{m}.{c}" for m, cs in self.models.items() for c in cs}

    @property
    def direct_pairs(self) -> set[tuple[str, str]]:
        return {(str(e["from"]), str(e["to"])) for e in self.direct}


def build_view(spec: Mapping[str, Any]) -> View:
    """Load a parsed spec. Indirect rows expand one by one; a bad row is recorded, not raised."""
    direct = rows(spec, "edges")
    indirect_rows = rows(spec, "indirect_edges")
    has_inventory = isinstance(spec.get("models"), Mapping) and isinstance(
        spec.get("seeds"), Mapping
    )
    if has_inventory:
        seeds = {s: list(cs or []) for s, cs in spec["seeds"].items()}
        models = {m: list((v or {}).get("columns") or []) for m, v in spec["models"].items()}
        depends_on = {m: list((v or {}).get("depends_on") or []) for m, v in spec["models"].items()}
    else:
        seen_seeds: dict[str, list[str]] = defaultdict(list)
        seen_models: dict[str, list[str]] = defaultdict(list)
        depends_on = {}
        for e in direct:
            for end, is_target in ((e.get("from"), False), (e.get("to"), True)):
                if not is_column_id(end):
                    continue
                t, c = str(end).split(".")
                inv = seen_models if is_target or not t.startswith("raw_") else seen_seeds
                if c not in inv[t]:
                    inv[t].append(c)
        seeds, models = dict(seen_seeds), dict(seen_models)
    view = View(spec, has_inventory, seeds, models, depends_on, direct, indirect_rows)
    direct_pairs = view.direct_pairs
    for row in indirect_rows:  # row by row, so one bad row does not hide the others
        try:
            exp = expand_indirect([row], models, direct_pairs)
        except (KeyError, ValueError) as err:
            view.expand_errors.append(f"{row.get('from')} -> {row.get('model')}: {err}")
            continue
        view.pairs += exp.pairs
        view.suppressed += exp.suppressed
        view.conflicts += exp.conflicts
    return view


# ------------------------------------------------------------------------------- gold answers
def compute_depths(v: View) -> dict[str, int | None]:
    """Longest direct-edge path from a seed column; None (n/a) when no direct path reaches a seed.

    Indirect edges never count (DESIGN_v2 §1). Raises ValueError on a cycle.
    """
    inputs: dict[str, list[str]] = defaultdict(list)
    for f, t in v.direct_pairs:
        inputs[t].append(f)
    seeds = v.seed_columns
    depth: dict[str, int | None] = {}
    state: dict[str, int] = {}  # 1 = on stack, 2 = done
    for start in sorted(v.model_columns):
        stack = [start]
        while stack:
            col = stack[-1]
            if col in depth:
                stack.pop()
                continue
            if col in seeds:
                depth[col] = 0
                stack.pop()
                continue
            state[col] = 1
            todo = [f for f in inputs.get(col, []) if f not in depth]
            for f in todo:
                if state.get(f) == 1:
                    raise ValueError(f"cycle through {f}")
            if todo:
                stack.extend(todo)
                continue
            ds = [d for d in (depth[f] for f in inputs.get(col, [])) if d is not None]
            depth[col] = max(ds) + 1 if ds else None
            state[col] = 2
            stack.pop()
    return {c: depth[c] for c in v.model_columns}


def _adjacency(v: View, include_indirect: bool, reverse: bool) -> dict[str, set[str]]:
    nxt: dict[str, set[str]] = defaultdict(set)
    pairs: list[tuple[str, str]] = list(v.direct_pairs)
    if include_indirect:
        pairs += [(x.from_column, x.to_column) for x in v.pairs]
    for f, t in pairs:
        if reverse:
            nxt[t].add(f)
        else:
            nxt[f].add(t)
    return nxt


def _closure(nxt: Mapping[str, set[str]], start: str) -> set[str]:
    seen: set[str] = set()
    todo = deque([start])
    while todo:
        for t in nxt.get(todo.popleft(), set()) - seen:
            seen.add(t)
            todo.append(t)
    return seen


def downstream(v: View, source: str, *, include_indirect: bool) -> set[str]:
    """Every column reachable from ``source`` (direct edges, plus indirect pairs if asked)."""
    return _closure(_adjacency(v, include_indirect, reverse=False), source)


def upstream(v: View, target: str, *, include_indirect: bool) -> set[str]:
    """Every column ``target`` is reachable from (direct edges, plus indirect pairs if asked)."""
    return _closure(_adjacency(v, include_indirect, reverse=True), target)


def reaches(v: View, source: str, target: str, *, include_indirect: bool) -> bool:
    return target in downstream(v, source, include_indirect=include_indirect)


def direct_inputs(v: View, target: str) -> list[Mapping[str, Any]]:
    """The direct spec edges into ``target``, sorted by source."""
    return sorted((e for e in v.direct if e["to"] == target), key=lambda e: str(e["from"]))


def indirect_inputs(v: View, target: str) -> list[IndirectPair]:
    """The expanded indirect pairs into ``target``, sorted by (source, type)."""
    return sorted(
        (x for x in v.pairs if x.to_column == target), key=lambda x: (x.from_column, x.type)
    )


def downstream_depth(v: View, column: str) -> int:
    """Longest direct-edge path leaving ``column`` (0: no direct edge reads it)."""
    nxt = _adjacency(v, include_indirect=False, reverse=False)
    memo: dict[str, int] = {}

    def walk(c: str) -> int:
        if c not in memo:
            memo[c] = max((1 + walk(t) for t in nxt.get(c, set())), default=0)
        return memo[c]

    return walk(column)


def longest_path(v: View, target: str, depths: Mapping[str, int | None]) -> list[str]:
    """One longest seed → ``target`` direct path: of all longest paths, the lexicographically
    largest (compared seed first), the tie-break DESIGN_v2 Appendix B uses. Empty when n/a."""
    inputs: dict[str, list[str]] = defaultdict(list)
    for f, t in v.direct_pairs:
        inputs[t].append(f)
    seeds = v.seed_columns
    memo: dict[str, list[str]] = {}

    def depth_of(c: str) -> int | None:
        return 0 if c in seeds else depths.get(c)

    def best(c: str) -> list[str]:
        if c not in memo:
            if c in seeds:
                memo[c] = [c]
            else:
                want = (depth_of(c) or 0) - 1
                memo[c] = max(best(f) for f in inputs[c] if depth_of(f) == want) + [c]
        return memo[c]

    return best(target) if depth_of(target) is not None else []


def models_of(columns: Iterable[str]) -> set[str]:
    return {c.split(".")[0] for c in columns}


def exposures_reached(models: Iterable[str], exposures: Mapping[str, Sequence[str]]) -> list[str]:
    """Exposure names (``{name: [model, ...]}``) that depend on any of ``models``."""
    hit = set(models)
    return sorted(name for name, deps in exposures.items() if hit & set(deps))


EDGE_LINE = re.compile(r"\{\s*from:\s*([\w.]+),\s*to:\s*([\w.]+)")


def edge_lines(spec_text: str) -> dict[tuple[str, str], int]:
    """1-based line of each direct edge row in the spec file's text (for citations in gold)."""
    found: dict[tuple[str, str], int] = {}
    for n, line in enumerate(spec_text.splitlines(), start=1):
        m = EDGE_LINE.search(line)
        if m:
            found.setdefault((m.group(1), m.group(2)), n)
    return found
