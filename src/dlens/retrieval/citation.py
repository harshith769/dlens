"""The citation a ledger attaches for a retrieved chunk (owner decision, S11).

A seed column is defined on its CSV's header line, but the chunker cites a seed column card as the
whole CSV at ``level: model`` (a CSV has no per-column line), which metrics M7 always scores as
invalid. ``chunk_citation`` cites such a card at the header line instead (line 1, ``level:
line``), and only when that line names the column as a whole word. Every other chunk keeps its
own citation.

This lives here, not in the chunker, on purpose: chunk ids hash the line range, so changing the
chunker's metadata changes ids and with them the rank tie-breaking the frozen linker sees. One
helper, used by every ledger that cites chunks (S1 now; S4 when ``search_docs`` is wired in, S12),
keeps S1 and S4 seed citations under the same rule. After the pilot the rule moves into the chunker.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from dlens.retrieval.chunks import Chunk


def _names(line: str, column: str) -> bool:
    return re.search(rf"(?<!\w){re.escape(column)}(?!\w)", line, re.IGNORECASE) is not None


def seed_header_citation(chunk: Chunk, project_dir: Path) -> dict[str, Any] | None:
    """Line 1 of the card's CSV, if ``chunk`` is a seed column card cited as the whole file and
    that header line names its column as a whole word; else None."""
    if not (
        chunk.kind == "column"
        and chunk.level == "model"
        and chunk.line_basis == "source"
        and chunk.file.endswith(".csv")
        and chunk.column
    ):
        return None
    root = project_dir.resolve()
    path = (root / chunk.file).resolve()
    if not path.is_relative_to(root) or not path.is_file():
        return None
    with path.open(encoding="utf-8", errors="replace") as fh:
        header = fh.readline().lstrip("﻿")
    if not _names(header, chunk.column.rsplit(".", 1)[-1]):
        return None
    return {"file": chunk.file, "line_start": 1, "line_end": 1, "level": "line"}


def chunk_citation(chunk: Chunk, project_dir: Path) -> dict[str, Any]:
    """The citation a ledger records for ``chunk``: the seed header line when it applies, else the
    chunk's own ``file``, lines and ``level``."""
    seed = seed_header_citation(chunk, project_dir)
    if seed is not None:
        return seed
    return {
        "file": chunk.file,
        "line_start": chunk.line_start,
        "line_end": chunk.line_end,
        "level": chunk.level,
    }
