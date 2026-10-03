import json
from pathlib import Path

import pytest

from dlens.agent.llm.tokens import estimate_tokens
from dlens.agent.llm.types import Message
from dlens.agent.tools import TOOL_SPECS, Toolbox, ToolResult
from dlens.agent.tools.budget import MAX_RESULT_TOKENS
from dlens.graph import LineageGraph
from dlens.lineage import Edge, EdgeKind

from .conftest import make_shop

TOTAL = "fct_star.total"


def tokens(result: ToolResult) -> int:
    """Tokens of the tool message exactly as the agent loop will send it."""
    return estimate_tokens([Message(role="tool", content=result.content)])


# -- trace_upstream ---------------------------------------------------------------------------


def test_trace_paths_and_side_records(toolbox: Toolbox) -> None:
    r = toolbox.call("trace_upstream", {"column_id": TOTAL})
    assert not r.is_error
    (path,) = r.llm_payload["paths"]
    assert [line.split(":")[0][:2] for line in path] == ["e_"] * 3
    assert "fct.total -> fct_star.total [IDENTITY]" in path[0]
    assert "[AGGREGATION: sum(amount)]" in path[1]
    assert "citation" not in json.dumps(r.llm_payload)  # citations are side records only
    edges = r.side_records["edges"]
    assert set(edges) == set(toolbox.emitted_ids) and len(edges) == 3
    assert all(e["citation"]["file"].startswith(("models/", "seeds/")) for e in edges.values())
    assert r.llm_payload["truncated"] is False and r.llm_payload["dropped"] == {"paths": 0}


def test_trace_accepts_suffix_and_full_ids_and_limits_depth(toolbox: Toolbox) -> None:
    full = toolbox.call("trace_upstream", {"column_id": "model.p.fct_star.total"})
    assert (
        full.llm_payload["paths"]
        == toolbox.call("trace_upstream", {"column_id": TOTAL}).llm_payload["paths"]
    )
    shallow = toolbox.call("trace_upstream", {"column_id": TOTAL, "max_depth": 1})
    assert len(shallow.llm_payload["paths"][0]) == 1 and shallow.llm_payload["depth_limited"]


def test_trace_of_a_seed_column_has_no_paths(toolbox: Toolbox) -> None:
    r = toolbox.call("trace_upstream", {"column_id": "raw.amt"})
    assert r.llm_payload["paths"] == [] and "notes" in r.llm_payload


def test_indirect_flag_is_explained(toolbox: Toolbox) -> None:
    r = toolbox.call("trace_upstream", {"column_id": TOTAL, "include_indirect": True})
    assert "indirect" in " ".join(r.llm_payload["notes"])


# -- impact_downstream ------------------------------------------------------------------------


def test_impact(toolbox: Toolbox) -> None:
    r = toolbox.call("impact_downstream", {"column_id": "raw.amt"})
    p = r.llm_payload
    assert [c["id"] for c in p["columns_by_depth"]["1"]] == ["stg.amount"]
    assert [c["id"] for c in p["columns_by_depth"]["3"]] == ["fct_star.total"]
    assert p["models"] == ["fct", "fct_star", "stg"]
    assert p["exposures"] == [{"name": "dash", "type": "dashboard"}]
    via = {c["via"] for d in p["columns_by_depth"].values() for c in d}
    assert via == set(r.side_records["edges"]) == set(toolbox.emitted_ids)
    cites = r.side_records["columns"]
    assert cites["fct_star.total"]["citation"]["level"] == "star"
    assert cites["stg.amount"]["citation"]["line_start"] == 3


def test_impact_depth_limited(toolbox: Toolbox) -> None:
    r = toolbox.call("impact_downstream", {"column_id": "raw.amt", "max_depth": 1})
    assert r.llm_payload["depth_limited"] and set(r.llm_payload["columns_by_depth"]) == {"1"}


# -- errors -----------------------------------------------------------------------------------


@pytest.mark.parametrize("tool", ["trace_upstream", "impact_downstream"])
def test_unknown_and_ambiguous_columns_are_error_objects(toolbox: Toolbox, tool: str) -> None:
    r = toolbox.call(tool, {"column_id": "fct_star.totl"})
    err = r.llm_payload["error"]
    assert err["code"] == "unknown_column" and "fct_star.total" in err["suggestions"]
    assert r.side_records == {} and toolbox.emitted_ids == frozenset()
    amb = toolbox.call(tool, {"column_id": "x_id"})  # bare names are rejected, never guessed
    assert amb.llm_payload["error"]["code"] == "unknown_column"


@pytest.mark.parametrize("bad", [0, -1, 99, "deep", 2.5, True, None])
def test_bad_depth_is_an_error_object(toolbox: Toolbox, bad: object) -> None:
    r = toolbox.call("trace_upstream", {"column_id": TOTAL, "max_depth": bad})
    assert r.llm_payload["error"]["code"] == "invalid_argument"


def test_numeric_strings_are_coerced_and_missing_args_reported(toolbox: Toolbox) -> None:
    assert not toolbox.call("trace_upstream", {"column_id": TOTAL, "max_depth": "2"}).is_error
    r = toolbox.call("trace_upstream", {})
    assert r.llm_payload["error"]["code"] == "invalid_argument"


def test_unknown_tool(toolbox: Toolbox) -> None:
    r = toolbox.call("drop_table", {})
    assert r.llm_payload["error"]["code"] == "unknown_tool"


# -- truncation -------------------------------------------------------------------------------


def wide_graph(n: int, tmp_path: Path) -> LineageGraph:
    cols = {"seed.p.src.root": {"model": "seed.p.src", "name": "root", "type": "int"}}
    models = {"seed.p.src": {"resource_type": "seed", "name": "src", "file": "seeds/src.csv"}}
    edges = []
    (tmp_path / "models").mkdir(exist_ok=True)
    for i in range(n):
        m, c = f"model.p.m{i:03d}", f"column_number_{i:03d}"
        cols[f"{m}.{c}"] = {"model": m, "name": c, "type": "int"}
        models[m] = {"resource_type": "model", "name": f"m{i:03d}", "file": f"models/m{i:03d}.sql"}
        (tmp_path / f"models/m{i:03d}.sql").write_text(f"select root as {c} from x\n")
        edges.append(
            Edge(
                from_column="seed.p.src.root",
                to_column=f"{m}.{c}",
                kind=EdgeKind.TRANSFORMATION,
                expression=f"root + {i}",
                file=f"models/m{i:03d}.sql",
                lines=(1, 1),
            )
        )
    return LineageGraph(
        columns=cols, edges=edges, depends_on=[], consumes=[], models=models,
        exposures={}, parse={}, deferred=[],
    )  # fmt: skip


def test_impact_truncates_under_the_cap(tmp_path: Path) -> None:
    box = Toolbox(wide_graph(150, tmp_path), tmp_path)
    r = box.call("impact_downstream", {"column_id": "src.root"})
    p = r.llm_payload
    kept = sum(len(v) for v in p["columns_by_depth"].values())
    assert p["truncated"] is True
    assert 0 < kept < 150 and p["dropped"]["columns"] == 150 - kept
    assert tokens(r) <= MAX_RESULT_TOKENS
    # no dangling ids: everything shown has a side record, nothing unseen was emitted
    via = {c["via"] for v in p["columns_by_depth"].values() for c in v}
    assert via == set(r.side_records["edges"]) == set(box.emitted_ids)
    assert set(r.side_records["columns"]) == {
        c["id"] for v in p["columns_by_depth"].values() for c in v
    }


def test_trace_truncates_under_the_cap(tmp_path: Path) -> None:
    g = wide_graph(120, tmp_path)
    box = Toolbox(g, tmp_path)
    # a column fed by every wide column: 120 two-edge-free paths, too many to fit
    r = box.call("trace_upstream", {"column_id": "m000.column_number_000"})
    assert not r.llm_payload["truncated"]  # one path: fits
    big = make_fan_in(120, tmp_path)
    r = Toolbox(big, tmp_path).call("trace_upstream", {"column_id": "sink.total"})
    p = r.llm_payload
    assert p["truncated"] and p["n_paths"] == 120
    assert p["dropped"]["paths"] == 120 - len(p["paths"]) > 0
    assert tokens(r) <= MAX_RESULT_TOKENS
    shown = {line.split(":")[0] for path in p["paths"] for line in path}
    assert shown == set(r.side_records["edges"])


def make_fan_in(n: int, tmp_path: Path) -> LineageGraph:
    (tmp_path / "models").mkdir(exist_ok=True)
    (tmp_path / "models/sink.sql").write_text("select a as total from t\n")
    cols = {"model.p.sink.total": {"model": "model.p.sink", "name": "total", "type": "int"}}
    models = {"model.p.sink": {"resource_type": "model", "name": "sink", "file": "models/sink.sql"}}
    edges = []
    for i in range(n):
        c = f"model.p.s{i:03d}.col_{i:03d}"
        cols[c] = {"model": f"model.p.s{i:03d}", "name": f"col_{i:03d}", "type": "int"}
        models[f"model.p.s{i:03d}"] = {"resource_type": "model", "name": f"s{i:03d}", "file": ""}
        edges.append(
            Edge(
                from_column=c, to_column="model.p.sink.total", kind=EdgeKind.AGGREGATION,
                expression=f"sum(col_{i:03d})", file="models/sink.sql", lines=(1, 1),
            )
        )  # fmt: skip
    return LineageGraph(
        columns=cols, edges=edges, depends_on=[], consumes=[], models=models,
        exposures={}, parse={}, deferred=[],
    )  # fmt: skip


# -- get_model_sql ----------------------------------------------------------------------------


def test_sql_whole_file(toolbox: Toolbox) -> None:
    r = toolbox.call("get_model_sql", {"model_id": "stg"})
    p = r.llm_payload
    assert p["file"] == "models/stg.sql" and p["excerpt_range"] == [1, 4]
    assert p["excerpt"][1] == "2:     id as x_id,"
    assert p["truncated"] is False and p["total_lines"] == 4
    assert p["excerpt_id"] in toolbox.emitted_ids
    rec = toolbox.record(p["excerpt_id"])
    assert rec is not None and rec["citation"]["line_end"] == 4


def test_sql_around_column_uses_source_lines_not_compiled(toolbox: Toolbox) -> None:
    r = toolbox.call("get_model_sql", {"model_id": "fct", "around_column": "total"})
    p = r.llm_payload
    assert p["excerpt_range"] == [1, 6]  # the column is on line 3 (line 1 is a comment); +/-3
    assert any(line.startswith("3:") and "sum(amount)" in line for line in p["excerpt"])
    assert r.side_records["column_citation"]["line_start"] == 3


def test_sql_id_forms_and_errors(toolbox: Toolbox) -> None:
    assert not toolbox.call("get_model_sql", {"model_id": "model.p.stg"}).is_error
    r = toolbox.call("get_model_sql", {"model_id": "stgg"})
    assert r.llm_payload["error"]["code"] == "unknown_model"
    assert "stg" in r.llm_payload["error"]["suggestions"]
    r = toolbox.call("get_model_sql", {"model_id": "raw"})
    assert r.llm_payload["error"]["code"] == "not_sql"
    r = toolbox.call("get_model_sql", {"model_id": "stg", "around_column": "amnt"})
    assert r.llm_payload["error"]["code"] == "unknown_column"
    assert r.llm_payload["error"]["suggestions"][0] == "amount"


def test_sql_truncates_long_files(tmp_path: Path) -> None:
    body = "\n".join(f"    column_{i:04d} + {i} as expression_number_{i:04d}," for i in range(400))
    (tmp_path / "models").mkdir()
    (tmp_path / "models/big.sql").write_text(f"select\n{body}\n    1 as last\nfrom t\n")
    g = LineageGraph(
        columns={"model.p.big.last": {"model": "model.p.big", "name": "last", "type": "int"}},
        edges=[], depends_on=[], consumes=[],
        models={"model.p.big": {"resource_type": "model", "name": "big", "file": "models/big.sql"}},
        exposures={}, parse={}, deferred=[],
    )  # fmt: skip
    r = Toolbox(g, tmp_path).call("get_model_sql", {"model_id": "big"})
    p = r.llm_payload
    assert p["truncated"] and p["dropped"]["lines"] > 0
    assert p["excerpt_range"][1] == len(p["excerpt"])  # range matches what is shown
    assert tokens(r) <= MAX_RESULT_TOKENS


def test_sql_never_reads_outside_the_project(shop_dir: Path) -> None:
    g = make_shop()
    (shop_dir.parent / "secret.sql").write_text("select 1")
    escaped = g.model_info("model.p.stg")
    assert escaped is not None
    g._models["model.p.stg"]["file"] = "../secret.sql"  # simulate a hostile manifest
    r = Toolbox(g, shop_dir).call("get_model_sql", {"model_id": "stg"})
    assert r.llm_payload["error"]["code"] == "not_sql"


# -- ledger -----------------------------------------------------------------------------------


def test_ledger_is_per_conversation(toolbox: Toolbox) -> None:
    first = toolbox.call("trace_upstream", {"column_id": TOTAL})
    ids1 = set(toolbox.emitted_ids)
    assert ids1 and len(toolbox.log) == 1
    toolbox.reset()
    assert toolbox.emitted_ids == frozenset() and toolbox.log == []
    assert toolbox.record(next(iter(ids1))) is None
    toolbox.call("impact_downstream", {"column_id": "raw.id"})
    ids2 = set(toolbox.emitted_ids)
    assert ids2 and not ids1 & ids2
    # same query again in a fresh conversation is emitted again
    toolbox.reset()
    again = toolbox.call("trace_upstream", {"column_id": TOTAL})
    assert again.llm_payload == first.llm_payload and toolbox.emitted_ids == ids1


def test_log_keeps_payload_and_side_records_separate(toolbox: Toolbox) -> None:
    toolbox.call("trace_upstream", {"column_id": TOTAL})
    entry = toolbox.log[0].model_dump()
    assert set(entry) == {"tool", "args", "llm_payload", "side_records"}
    assert "edges" in entry["side_records"] and "edges" not in entry["llm_payload"]


def test_ids_not_shown_are_not_emitted(tmp_path: Path) -> None:
    box = Toolbox(wide_graph(150, tmp_path), tmp_path)
    r = box.call("impact_downstream", {"column_id": "src.root"})
    assert len(box.emitted_ids) == len(r.side_records["edges"]) < 150


# -- specs ------------------------------------------------------------------------------------


def test_specs_match_tools() -> None:
    names = {s.name for s in TOOL_SPECS}
    assert names == {"resolve_entity", "trace_upstream", "impact_downstream", "get_model_sql"}
    for s in TOOL_SPECS:
        assert s.parameters["type"] == "object" and s.parameters["required"]
        assert set(s.parameters["required"]) <= set(s.parameters["properties"])
    assert estimate_tokens([], TOOL_SPECS) <= 450  # the four specs ride on every tool-phase call


def test_specs_hide_optional_args_the_tools_still_accept(toolbox: Toolbox) -> None:
    props = {s.name: set(s.parameters["properties"]) for s in TOOL_SPECS}
    assert "k" not in props["resolve_entity"]
    assert "include_indirect" not in props["trace_upstream"] | props["impact_downstream"]
    assert not toolbox.call("resolve_entity", {"text": "amount", "k": 1}).is_error
    assert not toolbox.call(
        "trace_upstream", {"column_id": "fct.total", "include_indirect": True}
    ).is_error


def test_edge_string_matches_the_tool_payload(toolbox: Toolbox) -> None:
    r = toolbox.call("trace_upstream", {"column_id": "fct.total"})
    line = r.llm_payload["paths"][0][0]
    eid = line.split(":", 1)[0]
    assert toolbox.edge_string(eid) == line
    assert toolbox.edge_string("e_00000000") is None
