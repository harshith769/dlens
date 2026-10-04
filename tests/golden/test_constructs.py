"""One golden test per SQL construct.

Each ``fixtures/<name>.expected.json`` is written by reasoning from the SQL and the strongest-kind
rule (DESIGN.md) BEFORE the engine runs on it. If the engine disagrees, decide who is wrong: fix
the engine, or mark the fixture unsupported with a top-level ``"xfail": "<reason>"`` key (strict;
``"xfail_indirect"`` marks only the indirect-edge test).
Never edit an expected file to match output; a deliberate change needs a one-line
``"justification"`` in the file, which this test requires to be non-empty when present.
"""

import pytest
from _harness import (
    cited_chunk,
    expected_indirect,
    fixture_names,
    key_is_cited,
    load_expected,
    run_fixture,
)


def _param(name: str, key: str = "xfail") -> object:
    """``"xfail"`` marks the direct-edge test, ``"xfail_indirect"`` the indirect-edge test."""
    reason = load_expected(name).get(key)
    marks = [pytest.mark.xfail(strict=True, reason=str(reason))] if reason else []
    return pytest.param(name, id=name, marks=marks)


@pytest.mark.parametrize("name", [_param(n) for n in fixture_names()])  # type: ignore[misc]
def test_construct(name: str) -> None:
    exp = load_expected(name)
    if "justification" in exp:
        assert str(exp["justification"]).strip(), f"{name}: empty justification"
    got = run_fixture(name)
    want = {(e["from"], e["to"], e["kind"]) for e in exp["edges"]}  # type: ignore[attr-defined]
    assert got.edges == want
    assert got.quality == exp["quality"]
    assert got.constants == sorted(exp["constants"])  # type: ignore[arg-type]
    assert got.deferred == {tuple(d) for d in exp["deferred"]}  # type: ignore[attr-defined]


@pytest.mark.parametrize("name", [_param(n, "xfail_indirect") for n in fixture_names()])  # type: ignore[misc]
def test_indirect_edges(name: str) -> None:
    """Indirect edges (ADR 0020), compared as (from, to, type). Every fixture states them."""
    assert run_fixture(name).indirect == expected_indirect(name)


@pytest.mark.parametrize("name", fixture_names())
def test_indirect_edges_cite_the_clause_that_holds_their_key(name: str) -> None:
    """S04 rule over every fixture: an indirect edge cites its clause's lines in the source file
    (never the whole model), and those lines hold the key as written (a column, a position, ALL)."""
    got = run_fixture(name)
    for e in got.indirect_edges:
        assert not e.model_level_citation, e
        assert key_is_cited(e.key, cited_chunk(e, got.source)), (e.key, e.lines)


def test_at_least_fifteen_constructs() -> None:
    assert len(fixture_names()) >= 15


def test_support_matrix_in_doc_is_current() -> None:
    from pathlib import Path

    from _harness import MATRIX_END, MATRIX_START, support_matrix_md

    doc = (Path(__file__).parents[2] / "docs" / "explain" / "lineage.md").read_text()
    table = doc.split(MATRIX_START)[1].split(MATRIX_END)[0].strip()
    assert table == support_matrix_md(), "run: uv run python scripts/gen_support_matrix.py"
