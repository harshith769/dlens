"""Reciprocal rank fusion (Cormack, Clarke & Büttcher 2009): ``Σ 1 / (k + rank)``."""

from __future__ import annotations

RRF_K = 60
DEPTH = 100  # each ranked list is cut to its top DEPTH before fusion


def rrf(lists: list[list[str]], k: int = RRF_K, depth: int = DEPTH) -> list[tuple[str, float]]:
    """Fused ``(id, score)`` best first; ranks are 1-based; ties broken by id."""
    scores: dict[str, float] = {}
    for ranked in lists:
        for rank, item in enumerate(ranked[:depth], 1):
            scores[item] = scores.get(item, 0.0) + 1.0 / (k + rank)
    return sorted(scores.items(), key=lambda kv: (-kv[1], kv[0]))
