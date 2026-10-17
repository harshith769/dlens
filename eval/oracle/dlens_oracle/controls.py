"""Controls run before any perturbation (oracle-design.md §2).

(a) determinism: two independent base builds give identical fingerprints. A failure stops the run.
(b) row order: each parent rewritten with its own rows in a random order. A child column that
    changes is order-sensitive (a tie in a row_number / lag order key), and is flagged.
"""

import random
from dataclasses import dataclass, field

from dlens_oracle.build import Corpus, Warehouse


@dataclass
class OrderSensitivity:
    # child column (model.column) -> parents whose row order changed it
    columns: dict[str, list[str]] = field(default_factory=dict)


def determinism(corpus: Corpus, first: Warehouse) -> list[str]:
    """Tables whose fingerprints differ in a second, fresh build (empty: deterministic)."""
    second = Warehouse(corpus)
    try:
        a, b = first.base_fingerprints(), second.base_fingerprints()
    finally:
        second.close()
    return sorted(t for t in a if a[t] != b[t])


def row_order(wh: Warehouse, seed: int) -> OrderSensitivity:
    result = OrderSensitivity()
    base = {m: wh.table_fingerprint(m, "base") for m in wh.corpus.models}
    for parent, children in wh.corpus.children.items():
        if not children:
            continue
        order = list(range(len(wh.column_values(parent, next(iter(wh.types(parent)))))))
        random.Random(f"{seed}:{parent}:row_order").shuffle(order)
        wh.write_order(parent, order)
        try:
            for child in children:
                for column in wh.model_fingerprint(child).changed(base[child]):
                    result.columns.setdefault(f"{child}.{column}", []).append(parent)
        finally:
            wh.restore(parent)
    return result
