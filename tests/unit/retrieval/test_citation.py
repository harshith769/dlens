"""Ledger citation helper (S11 owner decisions): seed cards cite their CSV header line, YAML
descriptions cite their entry from its `- name:` line; every other chunk keeps its own range."""

import re
import sys
from collections import Counter
from dataclasses import replace
from pathlib import Path

import pytest

from dlens.retrieval.chunks import Chunk, ChunkSet
from dlens.retrieval.citation import (
    chunk_citation,
    seed_header_citation,
    yaml_entity,
    yaml_entry_citation,
)

from .conftest import SS_PROJECT

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "scripts"))
import citation_audit as audit  # noqa: E402


def _seed_cards(cs: ChunkSet) -> list:
    return [c for c in cs.chunks if c.kind == "column" and c.file.endswith(".csv")]


def test_every_seed_card_cites_its_header_line(ss_chunks: ChunkSet) -> None:
    seeds = _seed_cards(ss_chunks)
    assert len(seeds) == 73
    for c in seeds:
        assert c.level == "model"  # the chunker itself is unchanged
        cite = chunk_citation(c, SS_PROJECT)
        assert cite == {"file": c.file, "line_start": 1, "line_end": 1, "level": "line"}
        header = (SS_PROJECT / c.file).read_text().splitlines()[0]
        name = str(c.column).rsplit(".", 1)[1]
        assert re.search(rf"(?<!\w){re.escape(name)}(?!\w)", header, re.IGNORECASE)


def test_header_without_the_column_keeps_the_card_citation(
    ss_chunks: ChunkSet, tmp_path: Path
) -> None:
    card = _seed_cards(ss_chunks)[0]
    name = str(card.column).rsplit(".", 1)[1]
    (tmp_path / card.file).parent.mkdir(parents=True)
    # the name only as part of a longer field: not a whole word
    (tmp_path / card.file).write_text(f"x_{name}_y,other\n1,2\n")
    assert seed_header_citation(card, tmp_path) is None
    assert chunk_citation(card, tmp_path) == {
        "file": card.file,
        "line_start": card.line_start,
        "line_end": card.line_end,
        "level": "model",
    }


def _own(c) -> dict:
    return {"file": c.file, "line_start": c.line_start, "line_end": c.line_end, "level": c.level}


def test_sql_and_exposure_chunks_keep_their_citation(ss_chunks: ChunkSet) -> None:
    others = [c for c in ss_chunks.chunks if c.file.endswith(".sql") or c.doc_kind == "exposure"]
    assert {c.kind for c in others} == {"model", "column", "doc"}
    for c in others:
        assert seed_header_citation(c, SS_PROJECT) is None
        assert yaml_entry_citation(c, SS_PROJECT) is None
        assert chunk_citation(c, SS_PROJECT) == _own(c)


def _yaml_chunks(cs: ChunkSet) -> list:
    return [c for c in cs.chunks if yaml_entity(c) is not None]


def test_yaml_description_cites_its_entry_from_the_name_line(ss_chunks: ChunkSet) -> None:
    """Column cards with a description (113) and model descriptions (49): the ledger cites from
    the entry's `- name:` line through the end of the description, inside that one entry."""
    chunks = _yaml_chunks(ss_chunks)
    kinds = Counter(c.doc_kind for c in chunks)
    assert kinds == {"column_description": 113, "model_description": 49}
    for c in chunks:
        cite = chunk_citation(c, SS_PROJECT)
        lines = (SS_PROJECT / c.file).read_text().splitlines()
        span = lines[cite["line_start"] - 1 : cite["line_end"]]
        name = yaml_entity(c)
        assert cite["level"] == "line" and cite["line_end"] == c.line_end
        assert cite["line_start"] < c.line_start  # widened upwards only
        assert re.match(rf"^\s*-\s+name:\s*{name}\s*$", span[0])  # the entry's own head
        assert re.search(rf"(?<!\w){name}(?!\w)", "\n".join(span))
        head = len(span[0]) - len(span[0].lstrip())
        # no other entry starts inside the span: every later line is deeper than the head
        assert all(not ln.strip() or len(ln) - len(ln.lstrip()) > head for ln in span[1:])


def _write(tmp: Path, rel: str, text: str) -> None:
    (tmp / rel).parent.mkdir(parents=True, exist_ok=True)
    (tmp / rel).write_text(text)


def _card(rel: str, line: int, column: str = "model.p.m.amt") -> Chunk:
    return Chunk(
        id="c_00000001", kind="column", doc_kind="column_description", model="model.p.m",
        column=column, file=rel, line_start=line, line_end=line, line_basis="source",
        level="line", title="m.amt · column", text="m.amt\ndescription: x",
    )  # fmt: skip


@pytest.mark.parametrize(
    ("yaml", "line", "want"),
    [
        # the usual shape: `- name:` heads the entry
        ("models:\n  - name: m\n    columns:\n      - name: amt\n        description: x\n", 5, 4),
        # the description is the entry's own `- ` line: not a description key, left unchanged
        ("cols:\n  - description: x\n    name: amt\n", 2, None),
        # `name:` as a later key of the entry: cite from the entry's head
        ("cols:\n  - tests: [a]\n    name: amt\n    description: x\n", 4, 2),
        # another column's entry: never borrowed
        ("cols:\n  - name: other\n    description: x\n", 3, None),
        # a sibling entry between: not the same entry
        ("cols:\n  - name: amt\n  - name: b\n    description: x\n", 4, None),
        # the cited line is not a description key
        ("cols:\n  - name: amt\n    tests: [x]\n", 3, None),
    ],
)
def test_yaml_entry_rule_cases(tmp_path: Path, yaml: str, line: int, want: int | None) -> None:
    _write(tmp_path, "models/schema.yml", yaml)
    card = _card("models/schema.yml", line)
    got = yaml_entry_citation(card, tmp_path)
    assert (got["line_start"] if got else None) == want
    assert chunk_citation(card, tmp_path) == (got or _own(card))


def test_audit_after_the_helper(ss_chunks: ChunkSet) -> None:
    """Every chunk the helper covers names its own entity inside its cited range; what is still
    missing is exactly the kinds the helper can't fix (star pass-through cards, 2 SQL chunks)."""
    covered = [
        c for c in ss_chunks.chunks
        if seed_header_citation(c, SS_PROJECT) or yaml_entry_citation(c, SS_PROJECT)
    ]  # fmt: skip
    assert len(covered) == 73 + 113 + 49
    result = audit.audit(ss_chunks.chunks, SS_PROJECT, chunk_citation)
    missing = {k: v["missing"] for k, v in result.items() if v["missing"]}
    assert missing == {"column card (SQL)": 19, "model chunk (SQL)": 2}
    for c in covered:
        names = audit.entity_names(c, {})
        assert audit.contains(audit.cited_lines(chunk_citation(c, SS_PROJECT), SS_PROJECT), names)


def test_path_outside_the_project_is_not_read(ss_chunks: ChunkSet) -> None:
    card = replace(_seed_cards(ss_chunks)[0], file="../../etc/x.csv")
    assert seed_header_citation(card, SS_PROJECT) is None
