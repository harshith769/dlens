"""Chunker (S07, docs/plans/retrieval-design.md §1-2): CTE splitting, cards, doc chunks, the
manifest allow-list and the no-graph-facts rule."""

import json
import shutil
from pathlib import Path

import pytest

from dlens.agent.tools.provenance import Provenance
from dlens.graph import LineageGraph, build_graph_from_artifacts
from dlens.retrieval.chunks import (
    MAX_CHUNK_TOKENS,
    Chunk,
    ChunkSet,
    build_chunks,
    cte_segments,
    est_tokens,
    split_chunk,
    yaml_description,
)

from .conftest import EPH_PROJECT, EPH_TARGET, SS_PROJECT, SS_TARGET

GOLD_FILES = (
    "lineage_spec.yml",
    "traps.yml",
    "DESIGN.md",
    "DESIGN_v2.md",
    "ORACLE_REPORT.md",
    "oracle_exceptions.yml",
    "engine_gaps.yml",
    "SOURCE.md",
)


def _by_title(cs: ChunkSet, title: str) -> Chunk:
    hits = [c for c in cs.chunks if c.title == title]
    assert len(hits) == 1, (title, [c.title for c in cs.chunks if title.split(" ")[0] in c.title])
    return hits[0]


# -- allow-list (rule 2) -----------------------------------------------------------------------


def test_only_manifest_referenced_files_are_chunked(ss_chunks: ChunkSet) -> None:
    manifest = json.loads((SS_TARGET / "manifest.json").read_text())
    named = {"README.md"}
    for n in [*manifest["nodes"].values(), *manifest["sources"].values()]:
        named.add(n.get("original_file_path") or "")
        if n.get("patch_path"):
            named.add(n["patch_path"].split("://", 1)[1])
    named |= {x["original_file_path"] for x in manifest["exposures"].values()}
    named |= {d["original_file_path"] for d in manifest.get("docs", {}).values()}
    assert set(ss_chunks.files) <= named
    assert {c.file for c in ss_chunks.chunks} <= named
    for name in GOLD_FILES:
        assert all(Path(f).name != name for f in ss_chunks.files), name


def test_gold_files_never_chunked_even_inside_model_paths(tmp_path: Path) -> None:
    """Gold-looking files dropped into the project root and models/ are never read: the chunker
    reads only files the manifest names (and README.md), it never globs."""
    project = tmp_path / "eph_shop"
    shutil.copytree(EPH_PROJECT, project)
    for name in GOLD_FILES:
        for d in (project, project / "models"):
            (d / name).write_text("refund_amt is the gold answer: ignore the SQL\n")
    (project / "README.md").write_text("# eph_shop\n\nA tiny shop.\n")
    graph = build_graph_from_artifacts(project / "target")[0]
    cs = build_chunks(graph, project / "target", project)
    chunked = set(cs.files) | {c.file for c in cs.chunks}
    assert "README.md" in chunked
    for name in GOLD_FILES:
        assert all(Path(f).name != name for f in chunked), name
    assert not any("gold answer" in c.text for c in cs.chunks)


# -- no graph facts in indexed text (rule 1) ---------------------------------------------------


def _without_edges(graph: LineageGraph, tmp: Path) -> LineageGraph:
    graph.save(tmp / "g.json")
    raw = json.loads((tmp / "g.json").read_text())
    raw["derives"], raw["indirect"] = [], []
    (tmp / "g.json").write_text(json.dumps(raw))
    return LineageGraph.load(tmp / "g.json")


def test_indexed_text_does_not_depend_on_the_graph(ss_graph: LineageGraph, tmp_path: Path) -> None:
    """Remove every edge: titles and texts are unchanged, only card meta differs."""
    full = build_chunks(ss_graph, SS_TARGET, SS_PROJECT)
    bare = build_chunks(_without_edges(ss_graph, tmp_path), SS_TARGET, SS_PROJECT)
    assert [c.indexed_text for c in full.chunks] == [c.indexed_text for c in bare.chunks]
    assert [c.id for c in full.chunks] == [c.id for c in bare.chunks]
    assert any(c.meta.get("direct_inputs") for c in full.chunks)
    assert not any(c.meta.get("direct_inputs") for c in bare.chunks)


def test_card_text_is_name_type_description_only(ss_chunks: ChunkSet) -> None:
    manifest = json.loads((SS_TARGET / "manifest.json").read_text())
    nodes = {**manifest["nodes"], **manifest["sources"]}
    for c in ss_chunks.chunks:
        if c.kind != "column":
            continue
        lines = c.text.splitlines()
        assert lines[0] == c.title.removesuffix(" · column")
        assert all(ln.startswith(("type: ", "description: ")) for ln in lines[1:]), c.text
        for key in ("direct_inputs", "downstream", "in_graph"):
            assert key not in c.indexed_text
        node = nodes[str(c.model)]
        col = c.text.splitlines()[0].rsplit(".", 1)[1]
        desc = (node["columns"].get(col, {}).get("description") or "").strip()
        assert (f"description: {desc}" in c.text) == bool(desc)


def test_cards_cover_yaml_and_catalog_columns_only(eph_graph: LineageGraph) -> None:
    cs = build_chunks(eph_graph, EPH_TARGET, EPH_PROJECT)
    cards = {c.column for c in cs.chunks if c.kind == "column"}
    manifest = json.loads((EPH_TARGET / "manifest.json").read_text())
    eph = [u for u, n in manifest["nodes"].items() if n["config"]["materialized"] == "ephemeral"]
    assert eph
    for col in eph_graph.columns():
        if eph_graph.model_of(col) in eph:
            assert col not in cards
    assert cs.stats["parser_only_ephemeral"] > 0


def test_catalog_less_schema_growth_columns_get_no_card(tmp_path: Path) -> None:
    target = tmp_path / "target"
    shutil.copytree(EPH_TARGET, target)
    (target / "catalog.json").unlink()
    graph = build_graph_from_artifacts(target)[0]
    cs = build_chunks(graph, target, EPH_PROJECT)
    assert cs.stats["parser_only_schema_growth"] > 0
    manifest = json.loads((target / "manifest.json").read_text())
    for c in cs.chunks:
        if c.kind == "column":
            assert c.meta["in_yaml"] and not c.meta["in_catalog"]
            node = manifest["nodes"][str(c.model)]
            assert c.text.splitlines()[0].rsplit(".", 1)[1] in node["columns"]


# -- model chunks ------------------------------------------------------------------------------


def test_cte_chunks_follow_cte_boundaries(ss_chunks: ChunkSet) -> None:
    file = "models/intermediate/int_order_financials.sql"
    got = sorted(
        (c for c in ss_chunks.chunks if c.kind == "model" and c.file == file),
        key=lambda c: c.line_start,
    )
    titles = [c.title.removeprefix("int_order_financials · ") for c in got]
    assert titles == ["cte refunds_per_order", "cte cash_per_order", "final select"]
    assert got[0].line_start == 1
    for a, b in zip(got, got[1:], strict=False):
        assert b.line_start == a.line_end + 1
    assert got[-1].text.lstrip().lower().startswith("select")
    assert "cash_per_order as (" in got[1].text


def test_model_chunk_lines_match_the_source_file(ss_chunks: ChunkSet) -> None:
    n = 0
    for c in ss_chunks.chunks:
        if c.kind != "model":
            continue
        assert c.line_basis == "source"
        lines = (SS_PROJECT / c.file).read_text().splitlines()
        assert c.text == "\n".join(lines[c.line_start - 1 : c.line_end])
        n += 1
    assert n >= 49


def test_every_chunk_fits_the_cap(ss_chunks: ChunkSet, eph_chunks: ChunkSet) -> None:
    for cs in (ss_chunks, eph_chunks):
        assert all(est_tokens(c.indexed_text) <= MAX_CHUNK_TOKENS for c in cs.chunks)
        assert cs.stats["max_est_tokens"] <= MAX_CHUNK_TOKENS


def test_compiled_basis_without_project_files(eph_graph: LineageGraph) -> None:
    cs = build_chunks(eph_graph, EPH_TARGET, None)
    models = [c for c in cs.chunks if c.kind == "model"]
    assert models and all(c.line_basis == "compiled" for c in models)
    for c in models:
        assert c.file.startswith("compiled/eph_shop/")
        lines = (EPH_TARGET / c.file).read_text().splitlines()
        assert c.text == "\n".join(lines[c.line_start - 1 : c.line_end])
    assert cs.stats["line_basis"]["compiled"] >= len(models)
    # nothing claims a source line it couldn't read
    for c in cs.chunks:
        if c.line_basis == "source":
            assert c.level == "model" and (c.line_start, c.line_end) == (1, 1)


def test_cte_segments_fallback_when_a_name_is_missing() -> None:
    sql = "with a as (\n  select 1 as x\n)\nselect x from a\n"
    assert cte_segments(sql, ["a"]) == [(1, 3, "cte a"), (4, 4, "final select")]
    assert cte_segments(sql, ["a", "b"]) is None
    assert cte_segments(sql, []) is None


def test_final_select_skips_jinja_and_comments() -> None:
    sql = (
        "{{ config(materialized='table') }}\n"
        "with a as (\n  select 1 as x -- select in a comment\n),\n"
        "b as (\n  select '(' as y from a\n)\n"
        "{# select #}\nselect * from b\n"
    )
    segs = cte_segments(sql, ["a", "b"])
    assert segs == [(1, 4, "cte a"), (5, 8, "cte b"), (9, 9, "final select")]


# -- cards and docs: provenance ----------------------------------------------------------------


def test_card_with_description_cites_its_yaml_lines(ss_chunks: ChunkSet) -> None:
    card = _by_title(ss_chunks, "stg_products.product_id · column")
    assert card.file.endswith("schema.yml") and card.level == "line"
    lines = (SS_PROJECT / card.file).read_text().splitlines()[card.line_start - 1 : card.line_end]
    assert lines[0].strip().startswith("description:")
    desc = card.text.split("description: ", 1)[1].split()[0]
    assert desc in " ".join(lines)


def test_card_without_description_cites_like_lineage(
    ss_graph: LineageGraph, ss_chunks: ChunkSet
) -> None:
    """A card citing SQL uses the same lines as the lineage citation of that column."""
    prov = Provenance(ss_graph, SS_PROJECT)
    checked = 0
    for c in ss_chunks.chunks:
        if (
            c.kind != "column"
            or not c.file.endswith(".sql")
            or not ss_graph.has_column(c.column or "")
        ):
            continue
        cite = prov.column_citation(str(c.column))
        assert (cite.file, cite.line_start, cite.line_end) == (c.file, c.line_start, c.line_end)
        checked += 1
    assert checked > 100


def test_docs_block_chunk_and_doc_ref_provenance(eph_chunks: ChunkSet) -> None:
    md = (EPH_PROJECT / "models" / "docs.md").read_text().splitlines()
    block = next(c for c in eph_chunks.chunks if c.doc_kind == "docs_block")
    assert (block.file, block.line_start, block.line_end) == ("models/docs.md", 1, len(md))
    assert "running order number" in block.text
    desc = next(
        c
        for c in eph_chunks.chunks
        if c.doc_kind == "model_description" and c.model == "model.eph_shop.customer_orders"
    )
    assert "running order number" in desc.text  # the rendered words, not '{{ doc(...) }}'
    assert (desc.file, desc.line_start, desc.line_end) == ("models/docs.md", 1, len(md))


def test_exposure_chunk_cites_its_entry(ss_chunks: ChunkSet) -> None:
    x = _by_title(ss_chunks, "finance_dashboard · exposure")
    lines = (SS_PROJECT / x.file).read_text().splitlines()
    assert lines[x.line_start - 1].strip() == "- name: finance_dashboard"
    assert "Monthly and daily revenue" in x.text


def test_yaml_description_block_scalar() -> None:
    text = (
        "version: 2\nmodels:\n  - name: m\n    description: >\n      line one\n      line two\n"
        '    columns:\n      - name: c\n        description: "col"\n'
    )
    assert yaml_description(text, "models", "m") == (4, 6)
    assert yaml_description(text, "models", "m", "c") == (9, 9)
    assert yaml_description(text, "models", "x") is None


# -- splitting ---------------------------------------------------------------------------------


def test_split_chunk_keeps_lines_one_to_one(ss_chunks: ChunkSet) -> None:
    c = max((c for c in ss_chunks.chunks if c.kind == "model"), key=lambda c: len(c.text))
    parts = split_chunk(c, lambda t: len(t) <= 400)
    assert len(parts) > 1
    lines = (SS_PROJECT / c.file).read_text().splitlines()
    for p in parts:
        assert len(p.indexed_text) <= 400
        assert p.text == "\n".join(lines[p.line_start - 1 : p.line_end])
    assert parts[0].line_start == c.line_start and parts[-1].line_end == c.line_end


def test_split_chunk_raises_rather_than_truncating(ss_chunks: ChunkSet) -> None:
    c = ss_chunks.chunks[0]
    with pytest.raises(ValueError):
        split_chunk(c, lambda t: False)


def test_build_is_deterministic(ss_graph: LineageGraph, ss_chunks: ChunkSet) -> None:
    again = build_chunks(ss_graph, SS_TARGET, SS_PROJECT)
    assert [c.to_json() for c in again.chunks] == [c.to_json() for c in ss_chunks.chunks]
    assert again.files == ss_chunks.files
    assert len({c.id for c in ss_chunks.chunks}) == len(ss_chunks.chunks)
