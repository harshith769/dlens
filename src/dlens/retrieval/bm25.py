"""Sparse retrieval: bm25s (lucene variant) over identifier-aware tokens.

Tokens are lower-case runs of ``[a-z0-9]``. A dotted or underscored identifier also stays whole,
so ``fct_orders.revenue_finance`` gives ``fct``, ``orders``, ``revenue``, ``finance``,
``fct_orders``, ``revenue_finance`` and ``fct_orders.revenue_finance``. There is no stemming and
only a small stop list. Abbreviations (amt → amount) are the entity linker's job (S08). The index
is rebuilt in memory at load: milliseconds at this size, and no bm25s on-disk format to depend on.
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import numpy as np

K1 = 1.5
B = 0.75
STOP = frozenset(
    "a an and are as at be by does for from how in is it of on or that the this to was what "
    "when where which who why with".split()
)
_IDENT = re.compile(r"[a-z0-9_]+(?:\.[a-z0-9_]+)*")
_PART = re.compile(r"[a-z0-9]+")


def tokenize(text: str) -> list[str]:
    out: list[str] = []
    for ident in _IDENT.findall(text.lower()):
        parts = _PART.findall(ident)
        out += [p for p in parts if p not in STOP]
        if len(parts) > 1:
            out += [seg for seg in ident.split(".") if "_" in seg]
            if "." in ident:
                out.append(ident)
    return out


class Bm25:
    def __init__(self, texts: list[str]) -> None:
        import bm25s

        self._n = len(texts)
        self._bm = bm25s.BM25(method="lucene", k1=K1, b=B)
        corpus = [tokenize(t) or ["\x00empty"] for t in texts]
        self._bm.index(corpus, show_progress=False)

    def scores(self, query: str) -> np.ndarray:
        import numpy as np

        toks = tokenize(query)
        if not toks or self._n == 0:
            return np.zeros(self._n, dtype=np.float32)
        return np.asarray(self._bm.get_scores(toks), dtype=np.float32)
