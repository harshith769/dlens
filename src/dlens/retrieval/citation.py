"""The citation a ledger attaches for a retrieved chunk (owner decisions, S11).

The chunker's own ranges are right for search but sometimes cite lines that don't name the
chunk's entity. Metrics M7 needs a citation's lines to name the column a claim is about.
``chunk_citation`` corrects two kinds, found by ``scripts/citation_audit.py``, and keeps every
other chunk's own range:

* **Seed column card**: the chunker cites the whole CSV (``level: model``). The ledger cites the
  header line (line 1, ``level: line``), where the column is defined, if it names the column as a
  whole word.
* **YAML description** (a column card with a description, or a model's description): the chunker
  cites only the ``description:`` line(s). The ledger cites from the entry's ``- name: <name>``
  line through the end of the description, still inside the same YAML entry.

Each correction applies only when the corrected range really names the entity; otherwise the
chunk's own range is kept. Star pass-through column cards (the cited ``*`` line names no column)
and SQL chunks that name no entity can't be corrected this way and are left as they are.

This lives here, not in the chunker, on purpose: chunk ids hash the line range, so changing the
chunker's metadata changes ids and with them the rank tie-breaking the frozen linker sees. One
helper, used by every ledger that cites chunks (S1 now; S4 when ``search_docs`` is wired in, S12),
keeps S1 and S4 citations under the same rule. After the pilot the rules move into the chunker.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from dlens.retrieval.chunks import Chunk

_YAML = (".yml", ".yaml")


def _names(line: str, name: str) -> bool:
    return re.search(rf"(?<!\w){re.escape(name)}(?!\w)", line, re.IGNORECASE) is not None


def _read(chunk: Chunk, project_dir: Path) -> list[str] | None:
    if chunk.line_basis != "source":
        return None
    root = project_dir.resolve()
    path = (root / chunk.file).resolve()
    if not path.is_relative_to(root) or not path.is_file():
        return None
    return path.read_text(encoding="utf-8", errors="replace").lstrip("﻿").splitlines()


def _line(start: int, end: int, chunk: Chunk) -> dict[str, Any]:
    return {"file": chunk.file, "line_start": start, "line_end": end, "level": "line"}


def seed_header_citation(chunk: Chunk, project_dir: Path) -> dict[str, Any] | None:
    """Line 1 of the card's CSV, if ``chunk`` is a seed column card cited as the whole file and
    that header line names its column as a whole word; else None."""
    if not (
        chunk.kind == "column"
        and chunk.level == "model"
        and chunk.file.endswith(".csv")
        and chunk.column
    ):
        return None
    lines = _read(chunk, project_dir)
    if not lines or not _names(lines[0], chunk.column.rsplit(".", 1)[-1]):
        return None
    return _line(1, 1, chunk)


def yaml_entity(chunk: Chunk) -> str | None:
    """The name a YAML description chunk's entry is keyed by: the column of a described column
    card, the model of a model description; None for anything else."""
    if not chunk.file.endswith(_YAML) or chunk.level != "line":
        return None
    if chunk.kind == "column" and chunk.doc_kind == "column_description" and chunk.column:
        return chunk.column.rsplit(".", 1)[-1]
    if chunk.kind == "doc" and chunk.doc_kind in ("model_description", "source_description"):
        return (chunk.model or "").rsplit(".", 1)[-1] or None
    return None


def _indent(line: str) -> int:
    return len(line) - len(line.lstrip(" "))


def yaml_entry_citation(chunk: Chunk, project_dir: Path) -> dict[str, Any] | None:
    """From the entry's ``- name: <name>`` line through the end of the cited description, if the
    chunk cites a ``description:`` key inside a list entry named after its own entity; else
    None. Only that one entry is ever spanned."""
    name = yaml_entity(chunk)
    lines = _read(chunk, project_dir) if name else None
    if not name or not lines or not 1 <= chunk.line_start <= chunk.line_end <= len(lines):
        return None
    desc = lines[chunk.line_start - 1]
    if not desc.lstrip().startswith("description:"):
        return None
    key_indent = _indent(desc)
    name_key = re.compile(rf"^\s*(-\s+)?name:\s*['\"]?{re.escape(name)}['\"]?\s*(#.*)?$", re.I)
    named = False
    for i in range(chunk.line_start - 1, 0, -1):  # 1-based line i, scanning up
        line = lines[i - 1]
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        ind = _indent(line)
        if ind > key_indent:
            continue  # inside a sibling key's block (e.g. a block scalar or a tests list)
        if ind == key_indent:
            if line.lstrip().startswith("-"):
                return None  # a sibling entry at the key's level: not our entry
            named = named or name_key.match(line) is not None  # `name:` as a later key
            continue
        # ind < key_indent: the entry's own head, which must be the list item opening it
        stripped = line.lstrip()
        if not stripped.startswith("- ") or _indent(line) + 2 != key_indent:
            return None
        if name_key.match(line) or named:
            return _line(i, chunk.line_end, chunk)
        return None
    return None


def chunk_citation(chunk: Chunk, project_dir: Path) -> dict[str, Any]:
    """The citation a ledger records for ``chunk``: a corrected range when one applies (seed
    header line, YAML entry from its ``- name:`` line), else the chunk's own range."""
    fixed = seed_header_citation(chunk, project_dir) or yaml_entry_citation(chunk, project_dir)
    if fixed is not None:
        return fixed
    return {
        "file": chunk.file,
        "line_start": chunk.line_start,
        "line_end": chunk.line_end,
        "level": chunk.level,
    }
