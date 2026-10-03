from pathlib import Path

import pytest

import dlens.agent.tools.provenance as prov_mod
from dlens.agent.tools.provenance import Provenance, edge_id, excerpt_id
from dlens.graph import LineageGraph
from dlens.lineage import EdgeKind

from .conftest import P, edge, make_shop


def test_edge_id_format_and_determinism() -> None:
    e = make_shop().edges()[0]
    eid = edge_id(e)
    assert eid == edge_id(make_shop().edges()[0])
    assert eid.startswith("e_") and len(eid) == 10
    assert int(eid[2:], 16) >= 0


def test_edge_id_depends_on_endpoints_and_kind() -> None:
    a = edge("x.a", "x.b", EdgeKind.RENAME, "f.sql", (1, 1), "a")
    b = edge("x.a", "x.b", EdgeKind.IDENTITY, "f.sql", (1, 1), "a")
    c = edge("x.a", "x.c", EdgeKind.RENAME, "f.sql", (1, 1), "a")
    assert len({edge_id(a), edge_id(b), edge_id(c)}) == 3
    # location and expression are not part of the identity
    d = edge("x.a", "x.b", EdgeKind.RENAME, "other.sql", (9, 9), "zzz")
    assert edge_id(a) == edge_id(d)


def test_excerpt_id() -> None:
    assert excerpt_id("a.sql", 1, 5) == excerpt_id("a.sql", 1, 5)
    assert excerpt_id("a.sql", 1, 5) != excerpt_id("a.sql", 1, 6)
    assert excerpt_id("a.sql", 1, 5).startswith("s_")


def test_collision_is_detected(
    shop: LineageGraph, shop_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(prov_mod, "edge_id", lambda e: "e_00000000")
    with pytest.raises(ValueError, match="collision"):
        Provenance(shop, shop_dir)


def test_edge_citation_levels(shop: LineageGraph, shop_dir: Path) -> None:
    p = Provenance(shop, shop_dir)
    by_to = {e.to_column: e for e in shop.edges()}
    line = p.edge_citation(by_to[f"{P}.stg.amount"])
    assert (line.file, line.line_start, line.line_end, line.level) == (
        "models/stg.sql",
        3,
        3,
        "line",
    )
    star = p.edge_citation(by_to[f"{P}.fct_star.total"])
    assert (star.file, star.line_start, star.level) == ("models/star.sql", 1, "star")


def test_citation_downgrades_when_range_lacks_the_column(
    shop: LineageGraph, shop_dir: Path
) -> None:
    bad = edge(
        "seed.p.raw.amt", f"{P}.stg.amount", EdgeKind.RENAME, "models/stg.sql", (2, 2), "amt"
    )
    p = Provenance(shop, shop_dir)
    c = p.edge_citation(bad)  # line 2 is `id as x_id,`: no `amount`, no star
    assert (c.level, c.line_start, c.line_end) == ("model", 1, 4)


def test_missing_and_escaping_files_cite_the_model(shop: LineageGraph, shop_dir: Path) -> None:
    p = Provenance(shop, shop_dir)
    gone = edge("seed.p.raw.id", f"{P}.stg.x_id", EdgeKind.RENAME, "models/gone.sql", (2, 2), "id")
    assert p.edge_citation(gone).level == "model"
    assert p.source("../outside.sql") is None


def test_column_citation(shop: LineageGraph, shop_dir: Path) -> None:
    p = Provenance(shop, shop_dir)
    c = p.column_citation(f"{P}.fct.total")
    assert (c.file, c.line_start, c.line_end, c.level) == ("models/fct.sql", 3, 3, "line")
    seed = p.column_citation("seed.p.raw.amt")
    assert (seed.file, seed.level) == ("seeds/raw.csv", "model")
    star = p.column_citation(f"{P}.fct_star.x_id")
    assert star.level == "star"


def test_edge_string_has_expression_only_for_computed_kinds(
    shop: LineageGraph, shop_dir: Path
) -> None:
    p = Provenance(shop, shop_dir)
    by_to = {e.to_column: e for e in shop.edges()}
    s = p.edge_string(by_to[f"{P}.fct.total"])
    assert (
        s
        == f"{edge_id(by_to[f'{P}.fct.total'])}: stg.amount -> fct.total [AGGREGATION: sum(amount)]"
    )
    assert p.edge_string(by_to[f"{P}.fct.x_id"]).endswith("[IDENTITY]")
    long = edge("a.x", "b.y", EdgeKind.TRANSFORMATION, "f.sql", (1, 1), "x" * 100)
    assert "…]" in prov_mod.Provenance.edge_string(
        Provenance(shop, shop_dir),
        long.model_copy(update={"from_column": f"{P}.stg.x_id", "to_column": f"{P}.fct.x_id"}),
    )


def test_safe_read_blocks_escapes_and_reads_fresh(tmp_path) -> None:
    from dlens.agent.tools.provenance import safe_read

    root = tmp_path / "proj"
    (root / "models").mkdir(parents=True)
    (root / "models/a.sql").write_text("select 1")
    (tmp_path / "secret.sql").write_text("select 2")
    assert safe_read(root, "models/a.sql") == "select 1"
    assert safe_read(root, "../secret.sql") is None
    assert safe_read(root, "models/missing.sql") is None
    assert safe_read(root, "") is None
    (root / "models/a.sql").write_text("select 3")
    assert safe_read(root, "models/a.sql") == "select 3"  # no cache


def test_text_sha1_depends_on_the_range() -> None:
    from dlens.agent.tools.provenance import text_sha1

    text = "a\nb\nc\n"
    assert text_sha1(text, 1, 2) == text_sha1("a\nb\nzzz", 1, 2)
    assert text_sha1(text, 1, 2) != text_sha1(text, 2, 3)
