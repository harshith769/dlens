"""Check a hand-written gold lineage spec for internal consistency and against its design numbers.

    uv run python scripts/check_gold_spec.py              # synthetic_shop spec + spec_expected.yml
    uv run python scripts/check_gold_spec.py --spec other.yml             # structure only
    uv run python scripts/check_gold_spec.py --v1-spec v1.yml             # + v1 edges unchanged

Reads only YAML; never runs dlens or dbt. Without --expected only the structural checks run
(schema, endpoints, duplicates, direct/indirect overlap, depends_on, incoming edges). The expected
file holds the design's numbers (counts, depth histogram, Appendix B, reachability) and points at
the traps file. The v1-identity check runs only with --v1-spec (or a `v1_spec:` key). Indirect rows are expanded with dlens.gold_spec.expand_indirect
(DESIGN_v2 §10 D7). Exits 1 if a gated check fails; INFO lines are reported, never gated.
See docs/explain/gold-spec.md.
"""

import argparse
import sys
from collections import Counter, defaultdict, deque
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from dlens.gold_spec import ALL_TARGETS, INDIRECT_TYPES, IndirectPair, expand_indirect

ROOT = Path(__file__).parents[1]
DEFAULT_SPEC = ROOT / "corpora" / "synthetic_shop" / "lineage_spec.yml"
DEFAULT_EXPECTED = DEFAULT_SPEC.with_name("spec_expected.yml")
DIRECT_KINDS = ("IDENTITY", "RENAME", "TRANSFORMATION", "AGGREGATION")
EDGE_KEYS = {"from", "to", "kind", "phase", "traps"}
INDIRECT_REQUIRED = {"from", "model", "type", "phase", "targets"}
INDIRECT_OPTIONAL = {"traps", "via", "note"}
TOP_KEYS = {"seeds", "models", "edges", "indirect_edges"}
NA = "n/a"


@dataclass
class Check:
    name: str
    ok: bool
    details: list[str] = field(default_factory=list)
    gated: bool = True  # False: INFO, reported but never fails the run


def table(column: str) -> str:
    return column.split(".")[0]


def layer(model: str) -> str:
    return "stg" if model.startswith("stg_") else "int" if model.startswith("int_") else "mart"


def _is_id(value: object) -> bool:
    return isinstance(value, str) and len(value.split(".")) == 2 and all(value.split("."))


def _check(name: str, problems: list[str], gated: bool = True) -> Check:
    return Check(name, not problems, problems, gated)


# ----------------------------------------------------------------------------- loaded spec view
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


def _rows(spec: Mapping[str, Any], key: str) -> list[Mapping[str, Any]]:
    rows = spec.get(key) or []
    return [r for r in rows if isinstance(r, Mapping)] if isinstance(rows, list) else []


def build_view(spec: Mapping[str, Any]) -> View:
    direct = _rows(spec, "edges")
    indirect_rows = _rows(spec, "indirect_edges")
    has_inventory = isinstance(spec.get("models"), Mapping) and isinstance(
        spec.get("seeds"), Mapping
    )
    if has_inventory:
        seeds = {s: list(cs or []) for s, cs in spec["seeds"].items()}
        models = {m: list((v or {}).get("columns") or []) for m, v in spec["models"].items()}
        depends_on = {m: list((v or {}).get("depends_on") or []) for m, v in spec["models"].items()}
    else:
        seeds, models, depends_on = defaultdict(list), defaultdict(list), {}
        for e in direct:
            for end, inv in ((e.get("from"), None), (e.get("to"), models)):
                if not _is_id(end):
                    continue
                t, c = str(end).split(".")
                target = inv if inv is not None else (seeds if t.startswith("raw_") else models)
                if c not in target[t]:
                    target[t].append(c)
        seeds, models = dict(seeds), dict(models)
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


# ---------------------------------------------------------------------------- structural checks
def check_schema(spec: Mapping[str, Any]) -> Check:
    p: list[str] = []
    extra = set(spec) - TOP_KEYS
    if extra:
        p.append(f"unknown top-level keys {sorted(extra)}")
    if not isinstance(spec.get("edges"), list):
        p.append("`edges` must be a list")
    if ("seeds" in spec) != ("models" in spec):
        p.append("`seeds` and `models` come together (the column inventory)")
    for name, cols in (spec.get("seeds") or {}).items():
        if not isinstance(cols, list) or not all(isinstance(c, str) for c in cols):
            p.append(f"seed {name}: columns must be a list of names")
        elif len(set(cols)) != len(cols):
            p.append(f"seed {name}: duplicate columns")
    for name, v in (spec.get("models") or {}).items():
        if not isinstance(v, Mapping) or set(v) != {"depends_on", "columns"}:
            p.append(f"model {name}: needs exactly `depends_on` and `columns`")
            continue
        for key in ("depends_on", "columns"):
            vals = v[key]
            if not isinstance(vals, list) or not vals or not all(isinstance(x, str) for x in vals):
                p.append(f"model {name}: `{key}` must be a non-empty list of names")
            elif len(set(vals)) != len(vals):
                p.append(f"model {name}: duplicate entries in `{key}`")
    for i, e in enumerate(spec.get("edges") or []):
        where = f"edges[{i}]"
        if not isinstance(e, Mapping):
            p.append(f"{where}: not a mapping")
            continue
        if set(e) != EDGE_KEYS:
            p.append(f"{where}: keys {sorted(e)} != {sorted(EDGE_KEYS)}")
        if not (_is_id(e.get("from")) and _is_id(e.get("to"))):
            p.append(f"{where}: from/to must be table.column")
        if e.get("kind") not in DIRECT_KINDS:
            p.append(f"{where}: kind {e.get('kind')!r} not in {DIRECT_KINDS}")
        if e.get("phase") != "v0.1":
            p.append(f"{where}: direct edges are phase v0.1")
        if not isinstance(e.get("traps", []), list):
            p.append(f"{where}: traps must be a list")
    for i, r in enumerate(spec.get("indirect_edges") or []):
        where = f"indirect_edges[{i}]"
        if not isinstance(r, Mapping):
            p.append(f"{where}: not a mapping")
            continue
        if INDIRECT_REQUIRED - set(r) or set(r) - INDIRECT_REQUIRED - INDIRECT_OPTIONAL:
            p.append(f"{where}: keys {sorted(r)}; required {sorted(INDIRECT_REQUIRED)}")
        if not _is_id(r.get("from")):
            p.append(f"{where}: from must be table.column")
        if r.get("type") not in INDIRECT_TYPES:
            p.append(f"{where}: type {r.get('type')!r} not in {INDIRECT_TYPES}")
        if r.get("phase") != "v0.3":
            p.append(f"{where}: indirect edges are phase v0.3")
        t = r.get("targets")
        if t != ALL_TARGETS and not (
            isinstance(t, list)
            and t
            and all(isinstance(x, str) for x in t)
            and len(set(t)) == len(t)
        ):
            p.append(f"{where}: targets must be 'all' or a non-empty list of distinct names")
        if "via" in r and not isinstance(r["via"], str):
            p.append(f"{where}: via must be a string")
        if not isinstance(r.get("traps", []), list):
            p.append(f"{where}: traps must be a list")
    return _check("schema", p)


def check_endpoints(v: View) -> Check:
    if not v.has_inventory:
        return Check("endpoints", True, ["no column inventory: skipped"], gated=False)
    p: list[str] = []
    known_from = v.seed_columns | v.model_columns
    for e in v.direct:
        if e["from"] not in known_from:
            p.append(f"direct from {e['from']} is not an inventory column")
        if e["to"] not in v.model_columns:
            p.append(f"direct to {e['to']} is not a model column")
    for r in v.indirect_rows:
        if r.get("from") not in known_from:
            p.append(f"indirect from {r.get('from')} is not an inventory column")
    p += [f"indirect row {x}" for x in v.expand_errors]
    for s in v.seeds:
        if s in v.models:
            p.append(f"{s} is both a seed and a model")
    return _check("endpoints", p)


def check_duplicates(v: View) -> Check:
    p = [
        f"direct edge {f} -> {t} x{n}"
        for (f, t), n in _dups((e["from"], e["to"]) for e in v.direct)
    ]
    p += [
        f"indirect pair {f} -> {t} [{k}] x{n}"
        for (f, t, k), n in _dups((x.from_column, x.to_column, x.type) for x in v.pairs)
    ]
    return _check("no duplicate edges", p)


def _dups(keys: Iterable[tuple[str, ...]]) -> list[tuple[tuple[str, ...], int]]:
    return sorted((k, n) for k, n in Counter(keys).items() if n > 1)


def check_overlap(v: View) -> Check:
    p = [f"{f} -> {t} [{k}] is listed as a target but is a direct edge" for f, t, k in v.conflicts]
    return _check("no pair both direct and indirect", p)


def check_depends_on(v: View) -> Check:
    if not v.has_inventory:
        return Check("depends_on", True, ["no inventory: skipped"], gated=False)
    p: list[str] = []
    contributed: dict[str, set[str]] = defaultdict(set)
    sources = [(str(e["from"]), table(str(e["to"])), "direct") for e in v.direct]
    sources += [(str(r["from"]), str(r["model"]), "indirect") for r in v.indirect_rows]
    for src, model, what in sources:
        parents = v.depends_on.get(model, [])
        if table(src) not in parents:
            p.append(f"{what} edge {src} -> {model}: {table(src)} not in depends_on({model})")
        contributed[model].add(table(src))
    for model, parents in v.depends_on.items():
        for parent in parents:
            if parent not in v.seeds and parent not in v.models:
                p.append(f"depends_on({model}) names unknown {parent}")
            elif parent not in contributed[model]:
                p.append(f"depends_on({model}): {parent} contributes no edge")
    return _check("depends_on", p)


def check_incoming(v: View) -> Check:
    """DESIGN_v2 §10 D3: every model column has >= 1 incoming edge, direct or indirect."""
    fed = {t for _, t in v.direct_pairs} | {x.to_column for x in v.pairs}
    p = [f"{c} has no incoming edge" for c in sorted(v.model_columns - fed)]
    return _check("every model column has an incoming edge (D3)", p)


# -------------------------------------------------------------------------------------- depth
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


def check_depth(v: View, exp: Mapping[str, Any]) -> list[Check]:
    try:
        depth = compute_depths(v)
    except ValueError as err:
        return [Check("depth", False, [str(err)])]
    hist = Counter(NA if d is None else d for d in depth.values())
    want = {(NA if str(k) == NA else int(k)): n for k, n in exp["depth_histogram"].items()}
    p = [
        f"depth {k}: {hist.get(k, 0)} columns, expected {want.get(k, 0)}"
        for k in sorted(set(hist) | set(want), key=lambda k: (k == NA, 0 if k == NA else k))
        if hist.get(k, 0) != want.get(k, 0)
    ]
    na = sorted(c for c, d in depth.items() if d is None)
    if na != sorted(exp["depth_na"]):
        p.append(f"n/a columns {na}, expected {sorted(exp['depth_na'])}")
    checks = [_check("depth histogram (DESIGN_v2 §5)", p)]

    deep = {c: d for c, d in depth.items() if d is not None and d >= 6}
    rows = {r["column"]: r for r in exp["deep_columns"]}
    p = [f"{c}: depth {deep[c]}, not in Appendix B" for c in sorted(set(deep) - set(rows))]
    p += [
        f"{c}: Appendix B lists it, depth is {depth.get(c)}" for c in sorted(set(rows) - set(deep))
    ]
    p += [
        f"{c}: depth {deep[c]}, Appendix B says {rows[c]['hops']}"
        for c in sorted(set(deep) & set(rows))
        if deep[c] != rows[c]["hops"]
    ]
    pairs = v.direct_pairs
    for c, r in sorted(rows.items()):
        path = r["path"]
        if path[0] not in v.seed_columns or path[-1] != c or len(path) - 1 != r["hops"]:
            p.append(f"{c}: Appendix B path must run seed -> column in {r['hops']} hops")
        p += [
            f"{c}: path step {a} -> {b} is not a direct edge"
            for a, b in zip(path, path[1:])
            if (a, b) not in pairs
        ]
    by_model = Counter(table(c) for c in deep)
    want_m = exp.get("six_plus_by_model", {})
    p += [
        f"{m}: {by_model.get(m, 0)} columns at 6+, expected {want_m.get(m, 0)}"
        for m in sorted(set(by_model) | set(want_m))
        if by_model.get(m, 0) != want_m.get(m, 0)
    ]
    max_depth = max(deep.values(), default=0)
    if "max_depth" in exp and max_depth != exp["max_depth"]:
        p.append(f"max depth {max_depth}, expected {exp['max_depth']}")
    checks.append(_check("6+ hop columns and paths (DESIGN_v2 Appendix B)", p))
    return checks


# ------------------------------------------------------------------------------ design numbers
def check_counts(v: View, exp: Mapping[str, Any]) -> Check:
    c = exp["counts"]
    got_models = Counter(layer(m) for m in v.models)
    got_cols = Counter()
    for m, cs in v.models.items():
        got_cols[layer(m)] += len(cs)
    got = {
        "seeds": len(v.seeds),
        "seed_columns": len(v.seed_columns),
        "models": dict(got_models),
        "model_columns": dict(got_cols),
        "direct_edges": len(v.direct),
        "direct_kinds": dict(Counter(str(e["kind"]) for e in v.direct)),
    }
    p = [f"{k}: {got[k]}, expected {c[k]}" for k in got if k in c and got[k] != c[k]]
    p += [f"expected value for {k} missing in the expected file" for k in got if k not in c]
    return _check("counts (DESIGN_v2 §0, §2)", p)


def check_v1_identical(v: View, v1_spec: Mapping[str, Any]) -> Check:
    def key(e: Mapping[str, Any]) -> tuple[str, str, str, str]:
        return (str(e["from"]), str(e["to"]), str(e["kind"]), str(e["phase"]))

    old = Counter(key(e) for e in _rows(v1_spec, "edges"))
    v1_models = {table(k[1]) for k in old}
    new = Counter(key(e) for e in v.direct if table(str(e["to"])) in v1_models)
    p = [f"only in v1: {' '.join(k)}" for k in sorted((old - new).elements())]
    p += [f"only in v2: {' '.join(k)}" for k in sorted((new - old).elements())]
    return _check(f"v1 direct edges content-identical ({sum(old.values())} edges)", p)


def check_absent(v: View, exp: Mapping[str, Any]) -> Check:
    present = v.seed_columns | v.model_columns
    p = [
        f"{x['column']} exists ({x['why']})"
        for x in exp.get("absent_columns", [])
        if x["column"] in present
    ]
    return _check("absent columns (DESIGN_v2 §1, §3)", p)


def downstream(v: View, source: str, with_indirect: bool) -> set[str]:
    nxt: dict[str, set[str]] = defaultdict(set)
    for f, t in v.direct_pairs:
        nxt[f].add(t)
    if with_indirect:
        for x in v.pairs:
            nxt[x.from_column].add(x.to_column)
    seen: set[str] = set()
    todo = deque([source])
    while todo:
        for t in nxt[todo.popleft()] - seen:
            seen.add(t)
            todo.append(t)
    return seen


def check_reachability(v: View, exp: Mapping[str, Any]) -> Check:
    p: list[str] = []
    for x in exp.get("unreachable", []):
        for mode in x["modes"]:
            if mode not in ("direct", "direct+indirect"):
                p.append(f"unknown mode {mode}")
            elif x["to"] in downstream(v, x["from"], mode == "direct+indirect"):
                p.append(f"{x['from']} reaches {x['to']} ({mode}; {x['why']})")
    return _check("unreachable pairs (DESIGN_v2 §1, §9 dev-10)", p)


# ------------------------------------------------------------------------------------- traps
REF_KEYS = {
    "models",
    "columns",
    "edges",
    "paths",
    "indirect",
    "absent_edges",
    "absent_direct_edges",
    "depends_on",
    "column",
}


def _walk(node: Any, path: str) -> Iterable[tuple[str, str, Any]]:
    if isinstance(node, Mapping):
        for k, val in node.items():
            if k in REF_KEYS:
                yield path, str(k), val
            yield from _walk(val, f"{path}.{k}")
    elif isinstance(node, list):
        for i, val in enumerate(node):
            yield from _walk(val, f"{path}[{i}]")


def _arrow(s: str) -> tuple[str, str]:
    a, b = (x.strip() for x in s.split("->"))
    return a, b


def check_traps(v: View, traps: Mapping[str, Any]) -> list[Check]:
    columns = v.seed_columns | v.model_columns
    tables = set(v.seeds) | set(v.models)
    direct = v.direct_pairs
    any_pair = direct | {(x.from_column, x.to_column) for x in v.pairs}
    rows = {(str(r["from"]), str(r["model"]), str(r["type"])) for r in v.indirect_rows}
    p: list[str] = []
    for where, key, val in _walk(traps, "traps"):
        vals = val if isinstance(val, list) else [val]
        for x in vals:
            if key in ("models", "depends_on") and x not in tables:
                p.append(f"{where}.{key}: unknown model {x}")
            elif key in ("columns", "column") and x not in columns:
                p.append(f"{where}.{key}: unknown column {x}")
            elif key == "edges" and _arrow(x) not in any_pair:
                p.append(f"{where}.edges: {x} is not an edge in the spec")
            elif key == "paths":
                p += [
                    f"{where}.paths: {a} -> {b} is not a direct edge"
                    for a, b in zip(x, x[1:])
                    if (a, b) not in direct
                ]
            elif key == "indirect" and (x["from"], x["model"], x["type"]) not in rows:
                p.append(f"{where}.indirect: no {x['type']} row {x['from']} -> {x['model']}")
            elif key in ("absent_edges", "absent_direct_edges"):
                # no edge (direct or indirect / direct only) from a to column or model b
                a, b = _arrow(x)
                among = any_pair if key == "absent_edges" else direct
                hit = sorted(t for f, t in among if f == a and (t == b or table(t) == b))
                if a not in columns or (b not in columns and b not in tables):
                    p.append(f"{where}.{key}: unknown endpoint in {x}")
                elif hit:
                    p.append(f"{where}.{key}: {x} exists ({hit})")
    return [_check("traps reference spec models/columns/edges", p), trap_tag_report(v, traps)]


def trap_tag_report(v: View, traps: Mapping[str, Any]) -> Check:
    """INFO: compare `traps:` tags on spec edges with the edges each trap lists (not gated)."""
    listed: dict[str, set[tuple[str, str]]] = defaultdict(set)
    for trap in [*(traps.get("traps") or []), *(traps.get("extras") or [])]:
        for where, key, val in _walk(trap, ""):
            if key == "edges":
                listed[trap["id"]] |= {_arrow(x) for x in val}
            elif key == "paths":
                listed[trap["id"]] |= {(a, b) for path in val for a, b in zip(path, path[1:])}
    tagged: dict[str, set[tuple[str, str]]] = defaultdict(set)
    for e in v.direct:
        for t in e.get("traps") or []:
            tagged[t].add((str(e["from"]), str(e["to"])))
    d: list[str] = []
    for tid in sorted(set(listed) | set(tagged)):
        for f, t in sorted(listed[tid] - tagged[tid]):
            if (f, t) in v.direct_pairs:  # indirect pairs carry no per-pair tag
                d.append(f"{tid}: listed, not tagged: {f} -> {t}")
        d += [
            f"{tid}: tagged, not listed: {f} -> {t}" for f, t in sorted(tagged[tid] - listed[tid])
        ]
    return Check(f"trap tags vs traps file: {len(d)} mismatches", True, d, gated=False)


# ------------------------------------------------------------------------------------ reports
def indirect_report(v: View, v1_models: set[str]) -> Check:
    """INFO: indirect rows, expanded pairs and models per type, split v1 models / new models."""

    def stats(t: str, v1: bool) -> str:
        rows = [r for r in v.indirect_rows if r["type"] == t and (r["model"] in v1_models) == v1]
        pairs = [x for x in v.pairs if x.type == t and (table(x.to_column) in v1_models) == v1]
        return (
            f"{len(rows):>3} rows {len(pairs):>4} pairs {len({r['model'] for r in rows}):>2} models"
        )

    lines = [f"{'type':<12} {'v1 models':<28} {'new models':<28}"]
    for t in INDIRECT_TYPES:
        lines.append(f"{t:<12} {stats(t, True):<28} {stats(t, False):<28}")
    lines.append(f"{'total':<12} {len(v.indirect_rows)} rows, {len(v.pairs)} pairs")
    lines.append(f"pairs suppressed by D7 (direct edge wins): {len(v.suppressed)}")
    lines.append(
        f"distinct (from, to) pairs with any indirect type: "
        f"{len({(x.from_column, x.to_column) for x in v.pairs})}"
    )
    return Check("indirect edge counts (reported, not gated)", True, lines, gated=False)


# --------------------------------------------------------------------------------------- main
def check_spec(
    spec: Mapping[str, Any],
    expected: Mapping[str, Any] | None = None,
    v1_spec: Mapping[str, Any] | None = None,
    traps: Mapping[str, Any] | None = None,
) -> list[Check]:
    schema = check_schema(spec)
    if not schema.ok:
        return [schema]
    v = build_view(spec)
    checks = [
        schema,
        check_endpoints(v),
        check_duplicates(v),
        check_overlap(v),
        check_depends_on(v),
        check_incoming(v),
    ]
    if expected is not None:
        checks += [
            check_counts(v, expected),
            *check_depth(v, expected),
            check_absent(v, expected),
            check_reachability(v, expected),
        ]
    if v1_spec is not None:
        checks.append(check_v1_identical(v, v1_spec))
    if traps is not None:
        checks += check_traps(v, traps)
    v1_models = {table(str(e["to"])) for e in _rows(v1_spec or {}, "edges")}
    v1_models |= set((expected or {}).get("v1_models", []))
    checks.append(indirect_report(v, v1_models))
    return checks


def load(path: Path) -> Mapping[str, Any]:
    data = yaml.safe_load(path.read_text())
    if not isinstance(data, Mapping):
        raise SystemExit(f"{path}: not a YAML mapping")
    return data


def run(
    spec_path: Path,
    expected_path: Path | None = None,
    v1_spec_path: Path | None = None,
    traps_path: Path | None = None,
) -> list[Check]:
    """Load files and run every check. The expected file may name `v1_spec` and `traps` (paths
    relative to itself); explicit arguments win."""
    expected = load(expected_path) if expected_path else None
    if expected_path and expected:
        base = expected_path.parent
        if v1_spec_path is None and expected.get("v1_spec"):
            v1_spec_path = base / expected["v1_spec"]
        if traps_path is None and expected.get("traps"):
            traps_path = base / expected["traps"]
    return check_spec(
        load(spec_path),
        expected,
        load(v1_spec_path) if v1_spec_path else None,
        load(traps_path) if traps_path else None,
    )


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawTextHelpFormatter)
    ap.add_argument("--spec", type=Path, default=DEFAULT_SPEC)
    ap.add_argument(
        "--expected",
        type=Path,
        help="design numbers (default for the default spec: spec_expected.yml)",
    )
    ap.add_argument("--v1-spec", type=Path, help="v1 spec whose edges must be kept unchanged")
    ap.add_argument("--traps", type=Path, help="traps file whose references must exist")
    args = ap.parse_args()
    if args.expected is None and args.spec == DEFAULT_SPEC:
        args.expected = DEFAULT_EXPECTED
    checks = run(args.spec, args.expected, args.v1_spec, args.traps)
    print(f"spec: {args.spec}")
    for c in checks:
        status = "INFO" if not c.gated else "PASS" if c.ok else "FAIL"
        print(f"{status}  {c.name}" + ("" if c.ok or not c.gated else f": {len(c.details)}"))
        for line in c.details:
            print(f"        {line}")
    failed = [c for c in checks if c.gated and not c.ok]
    print(f"\n{len(failed)} gated check(s) failed" if failed else "\nall gated checks pass")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
