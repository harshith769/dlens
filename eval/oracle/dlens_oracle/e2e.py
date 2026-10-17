"""End-to-end check: perturb a seed column, re-run everything downstream (oracle-design.md §5).

The changed set is compared with the gold's transitive closure, direct-only and direct+indirect.
Unobserved closure members are split into explained (every gold path from the seed crosses a local
category-B pair) and unexplained; they are listed, not gated (ADR 0017).
"""

from collections.abc import Iterable
from dataclasses import dataclass

import duckdb

from dlens_oracle import modes as modes_mod
from dlens_oracle.build import BASE, Warehouse
from dlens_oracle.gold import Gold


@dataclass
class E2EResult:
    column: str
    changed: dict[str, list[str]]  # model column -> modes
    errors: dict[str, str]  # mode -> first error
    closure_direct: set[str]
    closure_all: set[str]
    category_a: list[str]
    indirect_only: list[str]
    unobserved_explained: list[str]
    unobserved_unexplained: list[str]


def e2e_check(
    wh: Warehouse,
    gold: Gold,
    local_b: set[tuple[str, str]],
    seed: int = modes_mod.SEED,
    seeds: Iterable[str] | None = None,
) -> list[E2EResult]:
    corpus = wh.corpus
    base = {m: wh.table_fingerprint(m, BASE) for m in corpus.models}
    model_columns = {f"{m}.{c}" for m in corpus.models for c in wh.types(m)}
    out = []
    for seed_table in seeds if seeds is not None else corpus.seeds:
        downstream = corpus.descendants(seed_table)
        for column in wh.types(seed_table):
            short = f"{seed_table}.{column}"
            sql_type = wh.types(seed_table)[column]
            values = wh.column_values(seed_table, column)
            changed: dict[str, list[str]] = {}
            errors: dict[str, str] = {}
            for mode in modes_mod.modes_for(sql_type):
                new = modes_mod.apply(mode, sql_type, values, short, seed)
                if new is None:
                    continue
                wh.write_column(seed_table, column, new)
                try:
                    for model in downstream:
                        wh.materialise(model)
                    for model in downstream:
                        for name in wh.table_fingerprint(model).changed(base[model]):
                            changed.setdefault(f"{model}.{name}", []).append(mode)
                except duckdb.Error as exc:
                    errors[mode] = str(exc).splitlines()[0]
                finally:
                    wh.restore(seed_table)
                    for model in downstream:
                        wh.restore(model)
            closure_d = gold.closure(short, include_indirect=False) & model_columns
            closure_a = gold.closure(short, include_indirect=True) & model_columns
            reachable_without_b = gold.closure(short, include_indirect=True, drop=local_b)
            unobserved = sorted(closure_a - set(changed))
            out.append(
                E2EResult(
                    column=short,
                    changed={k: sorted(v) for k, v in sorted(changed.items())},
                    errors=errors,
                    closure_direct=closure_d,
                    closure_all=closure_a,
                    category_a=sorted(set(changed) - closure_a),
                    indirect_only=sorted(set(changed) & (closure_a - closure_d)),
                    unobserved_explained=[c for c in unobserved if c not in reachable_without_b],
                    unobserved_unexplained=[c for c in unobserved if c in reachable_without_b],
                )
            )
    return out
