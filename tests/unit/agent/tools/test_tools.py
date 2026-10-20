import json
from pathlib import Path

import pytest

from dlens.agent.llm.tokens import estimate_tokens
from dlens.agent.llm.types import Message
from dlens.agent.tools import TOOL_SPECS, Toolbox, ToolResult
from dlens.agent.tools.budget import MAX_RESULT_TOKENS
from dlens.graph import LineageGraph
from dlens.lineage import Edge, EdgeKind, IndirectEdge, IndirectKind

from .conftest import GROUP_BY_X_ID, STG, make_shop

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


# -- impact_downstream ------------------------------------------------------------------------


def shown(p: dict) -> list[tuple[str, str]]:
    """(model.column, via id) for every impact item, in payload order."""
    return [tuple(it.rsplit(" ", 1)) for v in p["columns_by_depth"].values() for it in v]


def test_impact(toolbox: Toolbox) -> None:
    r = toolbox.call("impact_downstream", {"column_id": "raw.amt"})
    p = r.llm_payload
    assert list(p["columns_by_depth"]) == ["1 [direct]", "2 [direct]", "3 [direct]"]
    assert [n for n, _ in shown(p)] == ["stg.amount", "fct.total", "fct_star.total"]
    assert p["mode"] == "direct + indirect" and "more" not in p
    assert p["models"] == ["fct", "fct_star", "stg"]
    assert p["exposures"] == [{"name": "dash", "type": "dashboard"}]
    via = {v for _, v in shown(p)}
    assert via == set(r.side_records["edges"]) == set(toolbox.emitted_ids)
    cites = r.side_records["columns"]
    assert cites["fct_star.total"]["citation"]["level"] == "star"
    assert cites["stg.amount"]["citation"]["line_start"] == 3


def test_impact_depth_limited(toolbox: Toolbox) -> None:
    r = toolbox.call("impact_downstream", {"column_id": "raw.amt", "max_depth": 1})
    assert r.llm_payload["depth_limited"]
    assert set(r.llm_payload["columns_by_depth"]) == {"1 [direct]"}


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
        exposures={}, parse={},
    )  # fmt: skip


def test_impact_truncates_under_the_cap(tmp_path: Path) -> None:
    box = Toolbox(wide_graph(150, tmp_path), tmp_path)
    r = box.call("impact_downstream", {"column_id": "src.root"})
    p = r.llm_payload
    kept = len(shown(p))
    assert p["truncated"] is True
    assert 0 < kept < 150 and p["dropped"]["columns"] == 150 - kept
    assert tokens(r) <= MAX_RESULT_TOKENS
    # never silent: 150 - kept cut columns in 150 - kept models -> one collapsed line
    assert p["more"] == [f"+{150 - kept} more columns in {150 - kept} models (direct)"]
    # no dangling ids: everything shown has a side record, nothing unseen was emitted
    via = {v for _, v in shown(p)}
    assert via == set(r.side_records["edges"]) == set(box.emitted_ids)
    assert set(r.side_records["columns"]) == {n for n, _ in shown(p)}
    assert len(r.side_records["full"]["columns"]) == 150  # the full set, for code


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
        exposures={}, parse={},
    )  # fmt: skip


# -- get_model_sql ----------------------------------------------------------------------------


def test_sql_whole_file(toolbox: Toolbox) -> None:
    r = toolbox.call("get_model_sql", {"model_id": "stg"})
    p = r.llm_payload
    assert p["file"] == "models/stg.sql" and [w["range"] for w in p["windows"]] == [[1, 4]]
    assert p["excerpt"][1] == "2:     id as x_id,"
    assert p["truncated"] is False and p["total_lines"] == 4
    sid = p["windows"][0]["excerpt_id"]
    assert sid in toolbox.emitted_ids
    rec = toolbox.record(sid)
    assert rec is not None and rec["citation"]["line_end"] == 4
    import hashlib

    assert rec["text_sha1"] == hashlib.sha1(STG.rstrip("\n").encode()).hexdigest()


def test_sql_around_column_uses_source_lines_not_compiled(toolbox: Toolbox) -> None:
    r = toolbox.call("get_model_sql", {"model_id": "fct", "around_column": "total"})
    p = r.llm_payload
    # the column is on line 3 (line 1 is a comment); +/-3. `amount` is not aliased earlier in
    # fct.sql, so there is exactly one window.
    assert [w["range"] for w in p["windows"]] == [[1, 6]]
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
        exposures={}, parse={},
    )  # fmt: skip
    r = Toolbox(g, tmp_path).call("get_model_sql", {"model_id": "big"})
    p = r.llm_payload
    assert p["truncated"] and p["dropped"]["lines"] > 0
    assert p["windows"][0]["range"][1] == len(p["excerpt"])  # range matches what is shown
    assert tokens(r) <= MAX_RESULT_TOKENS


def test_sql_never_reads_outside_the_project(shop_dir: Path) -> None:
    g = make_shop()
    (shop_dir.parent / "secret.sql").write_text("select 1")
    escaped = g.model_info("model.p.stg")
    assert escaped is not None
    g._models["model.p.stg"]["file"] = "../secret.sql"  # simulate a hostile manifest
    r = Toolbox(g, shop_dir).call("get_model_sql", {"model_id": "stg"})
    assert r.llm_payload["error"]["code"] == "not_sql"


# -- get_model_sql: alias windows ------------------------------------------------------------

ALIASED = """with base as (
    select
        a + b as raw_sum,
        c as other
    from t
),
mid as (
    select
        case
            when raw_sum > 0 then raw_sum
            else 0
        end as clean_sum,
        other
    from base
)
select
    mid.other,
    coalesce(mid.clean_sum, 0) as final_sum
from mid
"""


def _aliased_box(tmp_path: Path, sql: str = ALIASED) -> Toolbox:
    (tmp_path / "models").mkdir(exist_ok=True)
    (tmp_path / "models/agg.sql").write_text(sql)
    g = LineageGraph(
        columns={
            "model.p.agg.final_sum": {"model": "model.p.agg", "name": "final_sum", "type": "int"},
            "model.p.agg.other": {"model": "model.p.agg", "name": "other", "type": "int"},
        },
        edges=[], depends_on=[], consumes=[],
        models={"model.p.agg": {"resource_type": "model", "name": "agg", "file": "models/agg.sql"}},
        exposures={}, parse={},
    )  # fmt: skip
    return Toolbox(g, tmp_path)


def test_sql_around_column_follows_aliases_into_ctes(tmp_path: Path) -> None:
    box = _aliased_box(tmp_path)
    r = box.call("get_model_sql", {"model_id": "agg", "around_column": "final_sum"})
    p = r.llm_payload
    # final_sum is line 18 (window 15-19 with +/-3 context, file ends at 19); it reads
    # clean_sum, a multi-line CASE item on lines 9-12, which reads raw_sum, defined on line 3.
    assert [w["range"] for w in p["windows"]] == [[3, 3], [9, 12], [15, 19]]
    assert p["excerpt"].count("…") == 2
    assert all(w["excerpt_id"] in box.emitted_ids for w in p["windows"])
    for w in p["windows"]:
        cite = box.record(w["excerpt_id"])["citation"]
        assert [cite["line_start"], cite["line_end"]] == w["range"]


def test_sql_alias_depth_is_capped(tmp_path: Path) -> None:
    chain = "\n".join(
        ["with c0 as (select 1 as v0)"]
        + [f", c{i} as (select v{i - 1} + 1 as v{i} from c{i - 1})" for i in range(1, 6)]
        + ["select", "", "", "", "    v5 as final_sum", "from c5"]
    )
    box = _aliased_box(tmp_path, chain)
    p = box.call("get_model_sql", {"model_id": "agg", "around_column": "final_sum"}).llm_payload
    shown = {int(x.split(":", 1)[0]) for x in p["excerpt"] if x != "…"}
    # v5 (line 6), v4 (line 5), v3 (line 4): three hops; v2 (line 3) is a fourth hop, not shown
    assert {4, 5, 6} <= shown and 3 not in shown


def test_sql_drops_deepest_alias_windows_first_under_the_cap(tmp_path: Path, monkeypatch) -> None:
    import dlens.agent.tools.sql as sql_mod

    box = _aliased_box(tmp_path)
    full = box.call("get_model_sql", {"model_id": "agg", "around_column": "final_sum"})
    monkeypatch.setattr(sql_mod, "MAX_RESULT_TOKENS", tokens(full) - 1)
    box.reset()
    p = box.call("get_model_sql", {"model_id": "agg", "around_column": "final_sum"}).llm_payload
    assert [w["range"] for w in p["windows"]] == [[9, 12], [15, 19]]  # raw_sum (depth 2) went
    assert p["truncated"] and p["dropped"]["windows"] == 1


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
    assert set(entry) == {"tool", "args", "llm_payload", "side_records", "code_initiated", "rule"}
    assert (entry["code_initiated"], entry["rule"]) == (False, None)  # the model's call
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


def test_sql_accepts_a_model_column_as_model_id(toolbox: Toolbox) -> None:
    # The model passed a column id as model_id (seen live): split into model + around_column.
    r = toolbox.call("get_model_sql", {"model_id": "fct.total"})
    assert not r.is_error and r.llm_payload["model"] == "fct"
    assert r.side_records["column_citation"]["line_start"] == 3  # around_column = total
    # an explicit around_column wins over the split part
    r = toolbox.call("get_model_sql", {"model_id": "fct.total", "around_column": "x_id"})
    assert r.side_records["column_citation"]["line_start"] == 4
    # the split column must exist: the usual structured unknown_column error
    r = toolbox.call("get_model_sql", {"model_id": "fct.nope"})
    assert r.llm_payload["error"]["code"] == "unknown_column"


def test_sql_unknown_model_with_a_dot_keeps_the_original_error(toolbox: Toolbox) -> None:
    r = toolbox.call("get_model_sql", {"model_id": "nope.total"})
    err = r.llm_payload["error"]
    assert err["code"] == "unknown_model" and "'nope.total'" in err["message"]


def test_trace_is_direct_by_default_and_honours_include_indirect(shop_dir: Path) -> None:
    """s12-design A5.1 (i): trace defaults to direct; the flag (not advertised) now traverses."""
    plain = Toolbox(make_shop(), shop_dir)
    mixed = Toolbox(make_shop([GROUP_BY_X_ID]), shop_dir)
    a = plain.call("trace_upstream", {"column_id": "fct.total"})
    b = mixed.call("trace_upstream", {"column_id": "fct.total"})
    assert (a.llm_payload, a.side_records) == (b.llm_payload, b.side_records)
    both = mixed.call("trace_upstream", {"column_id": "fct.total", "include_indirect": True})
    lines = [line for path in both.llm_payload["paths"] for line in path]
    assert any(line.endswith("stg.x_id -> fct.total [GROUP_BY]") for line in lines)
    eid = next(line.split(":", 1)[0] for line in lines if "[GROUP_BY]" in line)
    rec = mixed.record(eid)
    assert rec is not None and rec["indirect"] is True and rec["key"] == "stg.x_id"


def test_impact_direct_mode_ignores_indirect_edges(shop_dir: Path) -> None:
    plain = Toolbox(make_shop(), shop_dir)
    mixed = Toolbox(make_shop([GROUP_BY_X_ID]), shop_dir)
    a = plain.call("impact_downstream", {"column_id": "stg.x_id", "include_indirect": False})
    b = mixed.call("impact_downstream", {"column_id": "stg.x_id", "include_indirect": False})
    assert (a.llm_payload, a.side_records) == (b.llm_payload, b.side_records)
    assert a.llm_payload["mode"] == "direct"


def _indirect(src: str, dst: str, kind: IndirectKind, key: str) -> IndirectEdge:
    return IndirectEdge(
        from_column=f"model.p.{src}",
        to_column=f"model.p.{dst}",
        kind=kind,
        key=key,
        expression=f"{kind.value.lower()} {key}",
        file="models/fct.sql",
        lines=(6, 6),
        model_level_citation=False,
    )


def test_impact_labels_a_mixed_path_by_its_first_indirect_hop(shop_dir: Path) -> None:
    """raw.id -> stg.x_id (direct) -> fct.total (JOIN) -> fct_star.total (direct): fct.total and
    fct_star.total are labelled JOIN at their shortest-path depth; the all-direct x_id chain stays
    [direct]. side["full"] keeps the whole via chain."""
    join = _indirect("stg.x_id", "fct.total", IndirectKind.JOIN, "stg.x_id")
    box = Toolbox(make_shop([join]), shop_dir)
    r = box.call("impact_downstream", {"column_id": "raw.id"})
    groups = r.llm_payload["columns_by_depth"]
    assert {k: [it.split()[0] for it in v] for k, v in groups.items()} == {
        "1 [direct]": ["stg.x_id"],
        "2 [direct]": ["fct.x_id"],
        "2 [JOIN]": ["fct.total"],
        "3 [direct]": ["fct_star.x_id"],
        "3 [JOIN]": ["fct_star.total"],
    }
    full = r.side_records["full"]
    chain = full["columns"]["fct_star.total"]["chain"]
    assert len(chain) == 3 and [full["edges"][e].get("indirect", False) for e in chain] == [
        False,
        True,
        False,
    ]
    assert full["columns"]["fct_star.total"]["via"] == chain[-1]


def test_a_column_reachable_both_ways_is_listed_once_under_direct(shop_dir: Path) -> None:
    """fct_star.x_id: 3 direct hops from raw.id, or 2 through a FILTER on stg.x_id. Listed once,
    under [direct] at its direct depth."""
    filt = _indirect("stg.x_id", "fct_star.x_id", IndirectKind.FILTER, "fct.x_id")
    box = Toolbox(make_shop([filt]), shop_dir)
    p = box.call("impact_downstream", {"column_id": "raw.id"}).llm_payload
    names = [n for n, _ in shown(p)]
    assert names.count("fct_star.x_id") == 1
    assert "fct_star.x_id" in [it.split()[0] for it in p["columns_by_depth"]["3 [direct]"]]
    assert "2 [FILTER]" not in p["columns_by_depth"]


def test_more_lines_per_model_then_per_group() -> None:
    from dlens.agent.tools.impact import MAX_MORE_LINES, Reached, more_lines

    def x(depth: int, label: str, model: str, col: str) -> Reached:
        return Reached(col, f"{model}.{col}", model, depth, label, ())

    few = [x(2, "JOIN", "fct_a", "a"), x(2, "JOIN", "fct_a", "b"), x(2, "JOIN", "fct_b", "c")]
    assert more_lines(few) == [
        "+2 more columns in fct_a (JOIN)",
        "+1 more columns in fct_b (JOIN)",
    ]
    many = [x(1, "direct", f"m{i:02d}", "c") for i in range(MAX_MORE_LINES + 1)]
    assert more_lines(many) == [f"+{len(many)} more columns in {len(many)} models (direct)"]
