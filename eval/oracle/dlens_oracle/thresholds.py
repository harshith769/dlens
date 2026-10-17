"""Hand-written thresholds: coverage scan, probes, crossings, nearest values (oracle-design §4).

The thresholds file is written from the corpus SQL read as text. This module checks that it covers
every predicate-looking line of the compiled SQL, and measures how often each perturbation moves a
row across each threshold.
"""

import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from decimal import Decimal
from pathlib import Path
from typing import Any

import yaml

from dlens_oracle.build import Warehouse

THRESHOLDS = Path(__file__).parents[1] / "thresholds.yml"

# WHERE, CASE, FILTER (WHERE, HAVING, QUALIFY, IN (…), IS [NOT] NULL, LIKE, BETWEEN, and any
# comparison, including the `=` of JOIN … ON lines (so non-equi joins can't be missed).
SCAN = re.compile(
    r"\bwhere\b|\bcase\b|\bhaving\b|\bqualify\b|<|>|!=|\bbetween\b|\bis\s+(not\s+)?null\b"
    r"|\bin\s*\(|\blike\b|\s=\s",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class Threshold:
    id: str
    model: str
    lines: tuple[int, ...]
    predicate: str
    clause: str
    cutoffs: tuple[float, ...]
    inputs: tuple[str, ...]
    probe: str


@dataclass
class ThresholdFile:
    thresholds: list[Threshold]
    not_thresholds: list[dict[str, Any]] = field(default_factory=list)

    def by_input(self) -> dict[str, list[Threshold]]:
        out: dict[str, list[Threshold]] = {}
        for t in self.thresholds:
            for column in t.inputs:
                out.setdefault(column, []).append(t)
        return out


def load(path: Path = THRESHOLDS) -> ThresholdFile:
    raw = yaml.safe_load(path.read_text())
    items = [
        Threshold(
            id=t["id"],
            model=t["model"],
            lines=tuple(t["lines"]),
            predicate=t["predicate"],
            clause=t["clause"],
            cutoffs=tuple(t["cutoffs"]),
            inputs=tuple(t["inputs"]),
            probe=" ".join(t["probe"].split()),
        )
        for t in raw["thresholds"]
    ]
    return ThresholdFile(items, list(raw.get("not_thresholds") or []))


def scan(sql: str) -> list[tuple[int, str]]:
    """(line number, stripped text) of every predicate-looking line of a compiled model."""
    return [(i, line.strip()) for i, line in enumerate(sql.splitlines(), 1) if SCAN.search(line)]


def uncovered(models: Mapping[str, str], spec: ThresholdFile) -> list[str]:
    """Scan hits that are neither a threshold line nor a not_thresholds entry ("m:line: text")."""
    covered = {(t.model, line) for t in spec.thresholds for line in t.lines}
    covered |= {(n["model"], int(n["line"])) for n in spec.not_thresholds}
    return [
        f"{model}:{line}: {text}"
        for model, sql in models.items()
        for line, text in scan(sql)
        if (model, line) not in covered
    ]


def stale(models: Mapping[str, str], spec: ThresholdFile) -> list[str]:
    """Entries that point at a line the scan does not hit (the SQL moved or changed)."""
    hits = {(m, line) for m, sql in models.items() for line, _ in scan(sql)}
    entries = [(t.model, line, t.id) for t in spec.thresholds for line in t.lines]
    entries += [(n["model"], int(n["line"]), "not_thresholds") for n in spec.not_thresholds]
    return [f"{m}:{line} ({what})" for m, line, what in entries if (m, line) not in hits]


# ------------------------------------------------------------------------------------- probes
Outcomes = dict[object, object]


def run_probe(wh: Warehouse, t: Threshold) -> tuple[Outcomes, list[object]]:
    """(key -> outcome, values) of the probe on the current ``main`` tables."""
    rows = wh.con.execute(t.probe).fetchall()
    outcomes = {r[0]: r[2] for r in rows}
    if len(outcomes) != len(rows):
        raise ValueError(f"threshold {t.id}: probe keys are not unique")
    return outcomes, [r[1] for r in rows]


def crossings(base: Outcomes, now: Outcomes) -> int:
    """Keys present in both runs whose outcome differs."""
    return sum(1 for k, v in base.items() if k in now and now[k] != v)


def _plain(v: object) -> object:
    if isinstance(v, Decimal):
        return float(v)
    return v


def nearest(values: Sequence[object], cutoffs: Sequence[float]) -> list[dict[str, float | None]]:
    """Per cut-off: the nearest base value below, the count exactly at, and the nearest above."""
    plain = [_plain(v) for v in values if v is not None and not isinstance(v, bool | str)]
    numbers: list[float] = [n for n in plain if isinstance(n, int | float)]
    out = []
    for c in cutoffs:
        below = [n for n in numbers if n < c]
        above = [n for n in numbers if n > c]
        out.append(
            {
                "cutoff": c,
                "nearest_below": max(below) if below else None,
                "at_cutoff": sum(1 for n in numbers if n == c),
                "nearest_above": min(above) if above else None,
                "rows_below": len(below),
                "rows_above": len(above),
            }
        )
    return out
