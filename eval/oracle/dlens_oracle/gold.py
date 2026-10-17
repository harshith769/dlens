"""The gold side: lineage_spec.yml as one-hop pairs and closures (oracle-design.md §5).

Indirect rows are expanded with dlens.gold_spec.expand_indirect, the only D7 implementation. This
module reads the gold spec only; it never sees parser output.
"""

from collections.abc import Iterable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from dlens.gold_spec import INDIRECT_TYPES, expand_indirect


@dataclass
class Gold:
    seeds: dict[str, list[str]]
    models: dict[str, list[str]]
    depends_on: dict[str, list[str]]
    direct: dict[tuple[str, str], str]  # (from, to) -> kind
    indirect: dict[tuple[str, str], set[str]]  # (from, to) -> indirect types
    # (from, model, type) of rows with `targets: all` (row-set clauses in the final SELECT)
    row_set: set[tuple[str, str, str]] = field(default_factory=set)

    def labels(self, src: str, dst: str) -> set[str]:
        """Edge labels of a pair: its direct kind and/or its indirect types."""
        out = set(self.indirect.get((src, dst), set()))
        if (src, dst) in self.direct:
            out.add(self.direct[(src, dst)])
        return out

    def one_hop(self, src: str) -> dict[str, set[str]]:
        """to -> labels, for every gold pair from ``src`` (direct and expanded indirect)."""
        out: dict[str, set[str]] = {}
        for f, t in [*self.direct, *self.indirect]:
            if f == src:
                out[t] = self.labels(f, t)
        return out

    def direct_inputs(self, dst: str) -> set[str]:
        return {f for f, t in self.direct if t == dst}

    def closure(
        self, src: str, include_indirect: bool, drop: Iterable[tuple[str, str]] = ()
    ) -> set[str]:
        """Columns reachable from ``src`` (excluding ``src``), optionally without pairs ``drop``."""
        dropped = set(drop)
        pairs = set(self.direct) | (set(self.indirect) if include_indirect else set())
        nxt: dict[str, list[str]] = {}
        for f, t in pairs - dropped:
            nxt.setdefault(f, []).append(t)
        seen: set[str] = set()
        stack = [src]
        while stack:
            for t in nxt.get(stack.pop(), []):
                if t not in seen:
                    seen.add(t)
                    stack.append(t)
        seen.discard(src)
        return seen


def is_indirect_label(label: str) -> bool:
    return label in INDIRECT_TYPES


def load_gold(spec_path: Path) -> Gold:
    spec: dict[str, Any] = yaml.safe_load(spec_path.read_text())
    models = {name: list(m["columns"]) for name, m in spec["models"].items()}
    direct = {(e["from"], e["to"]): e["kind"] for e in spec["edges"]}
    rows = spec.get("indirect_edges") or []
    expansion = expand_indirect(rows, models, set(direct))
    indirect: dict[tuple[str, str], set[str]] = {}
    for p in expansion.pairs:
        indirect.setdefault((p.from_column, p.to_column), set()).add(p.type)
    row_set = {(r["from"], r["model"], r["type"]) for r in rows if r["targets"] == "all"}
    return Gold(
        seeds={name: list(cols) for name, cols in spec["seeds"].items()},
        models=models,
        depends_on={name: list(m.get("depends_on") or []) for name, m in spec["models"].items()},
        direct=direct,
        indirect=indirect,
        row_set=row_set,
    )
