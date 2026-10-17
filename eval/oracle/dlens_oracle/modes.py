"""Perturbation modes per column type (oracle-design.md §3).

A mode maps a column's base values (in rowid order) to new values of the same SQL type, or to
None when it does not apply (a remap on a column with one distinct value, say). "Half" is a row
subset drawn from ``random.Random(f"{seed}:{column}:{mode}")``, so every run is reproducible.
"""

import random
from collections import Counter
from collections.abc import Callable, Sequence
from datetime import date, timedelta
from decimal import ROUND_HALF_UP, Decimal

SEED = 20261017
Values = list[object]

INTEGER_TYPES = {"TINYINT", "SMALLINT", "INTEGER", "BIGINT", "HUGEINT"}
FLOAT_TYPES = {"FLOAT", "REAL", "DOUBLE"}


def type_class(sql_type: str) -> str:
    """integer | numeric | temporal | string | boolean | other, from a DuckDB type name."""
    t = sql_type.upper()
    if t in INTEGER_TYPES:
        return "integer"
    if t in FLOAT_TYPES or t.startswith("DECIMAL"):
        return "numeric"
    if t == "DATE" or t.startswith("TIMESTAMP"):
        return "temporal"
    if t == "VARCHAR":
        return "string"
    if t == "BOOLEAN":
        return "boolean"
    return "other"


# Modes that keep the column's value multiset (they only move values between rows). Every other
# mode changes values; oracle-design.md §2 "Errors" refers to these as value-changing modes.
MULTISET_PRESERVING = {"shuffle"}


def _half(n: int, rng: random.Random) -> set[int]:
    return set(rng.sample(range(n), n // 2)) if n > 1 else set(range(n))


def _map_half(values: Values, rng: random.Random, f: Callable[[object], object]) -> Values:
    half = _half(len(values), rng)
    return [f(v) if i in half and v is not None else v for i, v in enumerate(values)]


def _cross(
    values: Values,
    rng: random.Random,
    up: Callable[[object], object],
    down: Callable[[object], object],
) -> Values:
    half = _half(len(values), rng)
    return [None if v is None else up(v) if i in half else down(v) for i, v in enumerate(values)]


def _each(values: Values, f: Callable[[object], object]) -> Values:
    return [None if v is None else f(v) for v in values]


def _num(v: object) -> Decimal | float | int:
    assert isinstance(v, Decimal | float | int)
    return v


def _int(v: object) -> int:
    assert isinstance(v, int)
    return v


def _when(v: object) -> date:
    assert isinstance(v, date)  # datetime is a date subclass
    return v


def shuffle(values: Values, rng: random.Random) -> Values:
    out = list(values)
    rng.shuffle(out)
    return out


def null_out(values: Values, rng: random.Random) -> Values:
    half = _half(len(values), rng)
    return [None if i in half else v for i, v in enumerate(values)]


def _relabel(values: Values, rng: random.Random) -> Values:
    return _each(values, lambda v: _int(v) + 1_000_003)


def _int_scale(values: Values, rng: random.Random) -> Values:
    return _each(values, lambda v: _int(v) * 3)


def _int_cross(values: Values, rng: random.Random) -> Values:
    return _cross(values, rng, lambda v: _int(v) * 10, lambda v: -_int(v))


def _break(values: Values, rng: random.Random) -> Values:
    present = [_int(v) for v in values if v is not None]
    top = max(present, default=0)
    half = sorted(_half(len(values), rng))
    fresh = {i: top + 7 + k for k, i in enumerate(half)}
    return [fresh.get(i, v) if v is not None else v for i, v in enumerate(values)]


def _factor(v: object, factor: str) -> object:
    """``v * factor``; a Decimal keeps its scale (rounded half up, as DuckDB's cast does)."""
    x = _num(v)
    if isinstance(x, Decimal):
        return (x * Decimal(factor)).quantize(x, rounding=ROUND_HALF_UP)
    return x * float(factor)


def _plus(v: object) -> object:
    x = _num(v)
    return x + Decimal("7.31") if isinstance(x, Decimal) else x + 7.31


def _shift(values: Values, rng: random.Random) -> Values:
    return _each(values, _plus)


def _scale(values: Values, rng: random.Random) -> Values:
    return _each(values, lambda v: _factor(v, "1.5"))


def _num_cross(values: Values, rng: random.Random) -> Values:
    return _cross(values, rng, lambda v: _factor(v, "10"), lambda v: _factor(v, "0.1"))


def _date_shift(values: Values, rng: random.Random) -> Values:
    return _each(values, lambda v: _when(v) + timedelta(days=37))


def _date_cross(values: Values, rng: random.Random) -> Values:
    return _cross(
        values,
        rng,
        lambda v: _when(v) + timedelta(days=120),
        lambda v: _when(v) - timedelta(days=120),
    )


def _ranked(values: Values) -> list[object]:
    counts = Counter(v for v in values if v is not None)
    return [v for v, _ in sorted(counts.items(), key=lambda kv: (-kv[1], str(kv[0])))]


def _remap_existing(values: Values, rng: random.Random) -> Values | None:
    ranked = _ranked(values)
    if len(ranked) < 2:
        return None
    src, dst = ranked[0], ranked[1]
    return [dst if v == src else v for v in values]


def _remap_new(values: Values, rng: random.Random) -> Values | None:
    ranked = _ranked(values)
    if not ranked:
        return None
    return ["zz_oracle" if v == ranked[0] else v for v in values]


def _flip(values: Values, rng: random.Random) -> Values:
    return _each(values, lambda v: not v)


def _flip_subset(values: Values, rng: random.Random) -> Values:
    return _map_half(values, rng, lambda v: not v)


Mode = Callable[[Values, random.Random], Values | None]

MODES: dict[str, dict[str, Mode]] = {
    "integer": {
        "relabel": _relabel,
        "scale": _int_scale,
        "cross": _int_cross,
        "break": _break,
        "shuffle": shuffle,
        "null_out": null_out,
    },
    "numeric": {
        "shift": _shift,
        "scale": _scale,
        "cross": _num_cross,
        "shuffle": shuffle,
        "null_out": null_out,
    },
    "temporal": {
        "shift": _date_shift,
        "shuffle": shuffle,
        "cross": _date_cross,
        "null_out": null_out,
    },
    "string": {
        "remap_existing": _remap_existing,
        "remap_new": _remap_new,
        "shuffle": shuffle,
        "null_out": null_out,
    },
    "boolean": {"flip": _flip, "flip_subset": _flip_subset, "null_out": null_out},
    "other": {"shuffle": shuffle, "null_out": null_out},
}


def modes_for(sql_type: str) -> dict[str, Mode]:
    return MODES[type_class(sql_type)]


def apply(
    mode: str, sql_type: str, values: Sequence[object], column: str, seed: int = SEED
) -> Values | None:
    """New values for ``column`` (``table.column``) under ``mode``; None if it doesn't apply."""
    rng = random.Random(f"{seed}:{column}:{mode}")
    return modes_for(sql_type)[mode](list(values), rng)
