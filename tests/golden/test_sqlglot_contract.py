"""Golden test #0 (spec §7): the engine relies on lineage(None, ...) returning a dict."""

import sqlglot
from sqlglot.lineage import Node, lineage


def test_lineage_none_returns_dict_on_pinned_sqlglot() -> None:
    assert sqlglot.__version__ == "30.21.0"
    schema = {"db": {"main": {"t": {"id": "int", "amt": "int"}}}}
    result = lineage(
        None, "select id, amt * 2 as x from db.main.t", schema=schema, dialect="duckdb"
    )
    assert isinstance(result, dict)
    assert list(result) == ["id", "x"]
    assert all(isinstance(n, Node) for n in result.values())
