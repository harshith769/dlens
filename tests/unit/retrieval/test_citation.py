"""Seed-card citation helper (S11 owner decision): a seed column card is cited at its CSV header
line when that line names the column as a whole word; every other chunk keeps its own citation."""

import re
from dataclasses import replace
from pathlib import Path

from dlens.retrieval.chunks import ChunkSet
from dlens.retrieval.citation import chunk_citation, seed_header_citation

from .conftest import SS_PROJECT


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


def test_model_and_yaml_cards_keep_their_citation(ss_chunks: ChunkSet) -> None:
    others = [c for c in ss_chunks.chunks if not c.file.endswith(".csv")]
    assert {c.kind for c in others} == {"model", "column", "doc"}
    for c in others:
        assert seed_header_citation(c, SS_PROJECT) is None
        assert chunk_citation(c, SS_PROJECT) == {
            "file": c.file,
            "line_start": c.line_start,
            "line_end": c.line_end,
            "level": c.level,
        }


def test_path_outside_the_project_is_not_read(ss_chunks: ChunkSet) -> None:
    card = replace(_seed_cards(ss_chunks)[0], file="../../etc/x.csv")
    assert seed_header_citation(card, SS_PROJECT) is None
