# Explain: lineage graph and CLI (`src/dlens/graph/`)

## What it does
`build_graph(project_dir)` runs ingest and `extract_lineage`, then wraps the result in a
`LineageGraph`. The graph answers two questions:
- `upstream(col)`: every path from `col` back to the columns it comes from (`list[LineagePath]`,
  each path a chain of hops with kind, expression, file and lines).
- `downstream(col)`: an `ImpactResult` with affected columns by depth, the hop that reached each
  one, affected models, affected exposures (through CONSUMES) and a `truncated` flag.

A hop (`Hop = Edge | IndirectEdge`) is a DERIVES edge, or, with `include_indirect=True`, a
DEPENDS_ON_INDIRECT edge (S04). `hop_label` names it: `direct`, or the indirect type.

It also does `resolve("fct_orders.revenue_finance")` (short id → full id), `save`/`load` (sorted JSON)
and `parse_report()`. `dlens trace COLUMN` and `dlens impact COLUMN` print both as trees.

## How it works
1. **Nodes** are every catalog column (`LineageGraph.from_results`), so a column with no edges still
   exists. Node attributes are `model`, `name`, `type`. CONTAINS is that `model` attribute.
2. **Edges** are the engine's DERIVES edges in one `nx.DiGraph`, with the whole `Edge` stored on
   each. The engine already keeps one edge per `(from, to)`, so a DiGraph loses nothing.
   DEPENDS_ON and CONSUMES stay as sorted pair lists, because nothing traverses them.
   CONSUMES comes from the manifest's exposures, since `LineageResult` doesn't carry it.
3. **`upstream`** is a DFS over predecessors in sorted order. A path ends at a column with no
   upstream, or after `max_depth` hops (`depth_limited`). After `max_paths` (default 1000) it
   stops and sets `truncated`. Both flags live on `PathList`, a `list` subclass, so the return
   type is still a list.
4. **`downstream`** is a BFS, so a column reached by two routes gets its *shortest* depth and one
   `via` edge. Models come from the owners of affected columns. Exposures come from those models
   plus the root's own model (changing a column affects what reads its model).
   `truncated` means the frontier still had unseen successors at `max_depth`.
5. **`include_indirect`** (S04). Indirect edges live in a separate list outside the nx graph
   (`indirect_edges()`, indirect-edges.md), indexed once by `to` and by `from`. With the flag on,
   `_preds`/`_succs` add them after the direct edges:
   - One hop per indirect type. raw.y → fct.total by JOIN and by GROUP_BY gives two hops, so
     `upstream` gives two paths.
   - **`max_depth` counts every hop**, direct or indirect. This is the traversal limit. The "hop
     depth" of ADR 0020 ("indirect edges never count toward hop depth") is the gold/question
     depth metric, which stays direct-only (ADR 0020, Clarification S04).
   - At equal depth, `downstream`'s `via` keeps a direct edge over an indirect one, then the
     indirect types in `IndirectKind` order (`hop_rank`). The frontier keeps discovery order, as
     before, so default-off results are unchanged.
   - **Defaults follow spec §7**: `upstream(include_indirect=False)`,
     `downstream(include_indirect=True)`. Because a bare `downstream()` would now traverse
     indirect edges, every caller in dlens passes the flag explicitly. The CLI passes its
     `--include-indirect` option (default off). The agent loop and the tools pass False (the tools
     accept and ignore the argument), and so the validator, UI and demo see direct edges only
     until S10/S12. `tests/unit/test_traversal_calls.py` scans `src/`, `scripts/`, `eval/` and
     `demo/` and fails on any call without `include_indirect=`.
6. **`resolve`**: an exact id wins. Otherwise a query with a dot matches ids ending in
   `"." + query`, so `stg_orders.order_id` can't match `xstg_orders.order_id`. Several matches raise
   `AmbiguousColumn` listing the full ids. No match raises `ColumnNotFound` with the 3 closest
   short ids (`difflib`). Bare column names are rejected on purpose.
7. **Save** writes `json.dumps(indent=2, sort_keys=True)`, nodes sorted by id, edges by
   `(from, to)`, plus `version` (the cache-format number) and `dlens_version`. The same graph always gives the same bytes, so it diffs cleanly.
   `__eq__` compares that canonical dict, which is what the round-trip tests use.
8. **Cache** (`cache.py`): `target/dlens_graph.json` is used unless it is missing, older than
   `target/manifest.json`, or older than any file under `models/`, `seeds/`, `macros/`,
   `snapshots/`, `tests/` or `dbt_project.yml`. `--rebuild` forces a rebuild, which re-runs dbt.
   Format v3 (S03) adds `indirect`. Format v4 (S04) adds `citation_gaps` to the parse report and
   drops `deferred_indirect`. `load` accepts v2 files (no indirect edges, e.g. the demo bundle)
   and v3 files, while `load_or_build` rebuilds any cache whose format is not the current one.
   `load` also rejects a file whose `version` (format) or `dlens_version` differs from the running
   code, and `load_or_build` treats that as a miss and rebuilds, so an upgrade never serves a graph
   written by older code.
9. **Rendering** (`render.py`) merges paths that share a prefix, so each hop prints once. A hop
   shows the column, `[KIND]`, the expression (cut at 60 characters) and `file:lines`.
   Names are `model.column`, or the full id if two columns share that short form. An indirect
   hop shows `[indirect TYPE]` and its clause, cited at the clause's lines. Tree children are
   keyed by `(column, hop_rank)`, so one column reached by two indirect types prints both hops,
   and the summaries count the indirect hops. Without the flag, the output is byte-identical to
   S03.

## Why this design
- **NetworkX DiGraph with `Edge` objects as attributes**: traversal is a few lines, the provenance
  needed for a citation stays on the edge, and ~10³ columns fits in memory.
- **BFS for impact, DFS for trace**: impact asks "what breaks and how far", where the shortest
  distance is the useful number. Trace asks "every route", because different routes have different
  expressions to cite.
- **A path cap instead of an unbounded list**: path counts multiply with fan-in. The v0.3 corpus
  has columns where that is real, and a silent explosion would hang the CLI or the agent.
  Truncation is reported rather than hidden.
- **Source mtimes in the cache rule**: the manifest only changes when dbt runs, so checking it
  alone serves a stale graph after a SQL edit.
- **Both a format version and the package version in the header**: the format number catches a
  deliberate shape change; the package version catches the unplanned case (an engine fix that
  changes edges without changing the shape). Cost: one rebuild per upgrade. Rejected: format
  number alone (stale edges after an engine fix) and hashing the source (heavy for little gain).
- **JSON, sorted**: reviewable in a PR and diffable between runs; nothing is a source of truth
  (spec §6), the graph can always be rebuilt.
- **`from_results` is pure**: tests build graphs with no dbt, and only the integration tests pay for it.

## Alternatives rejected
- **Neo4j or any graph database**: a server to run and install for a few thousand nodes, and
  the queries are plain BFS/DFS. The spec treats stores as rebuildable, so a DB adds nothing.
- **Pickle (`graph.gpickle`, like dbt writes)**: not diffable, and loading a pickle runs code.
- **SQLite or Parquet**: queryable, but not reviewable line by line, and recursive SQL for
  traversal is harder to read than the Python.
- **Recompute on every command**: a full dbt run for each `trace`. The cache reduces it to ~0.3 s.
- **Cache check on the manifest only**: stale after source edits (above).
- **Accepting bare column names**: `order_id` matches dozens of columns; an error listing all of
  them is useless. Short `model.column` ids are unique in practice, and ambiguity is reported.
- **Returning `(paths, truncated)` tuples**: it would change the spec's `list[...]` return. The
  `PathList` subclass keeps the type.

## Known limits
- Indirect traversal widens results a lot. On synthetic_shop, `stg_products.product_id` (a
  join-key-only column) impacts 0 columns direct-only and 175 with indirect edges (max 8 hops),
  and the uncapped impact payload grows from ~125 to ~4,469 tokens, over both the 1,500-token
  tool cap and the 3K input cap (`scripts/measure_indirect_reach.py`). That is why the tools stay
  direct-only until S10/S12 decide how to rank or trim indirect results.
- `upstream` enumerates paths, not a DAG summary. The cap bounds the work, but a capped trace
  shows an arbitrary 1000 of the paths (sorted DFS order), not the "most important" ones.
- The cache can't see changes outside the listed directories (for example a package update).
  Use `--rebuild`.

## Explain-back questions
1. `downstream` uses BFS and `upstream` uses DFS. For a column reachable by two routes of length 2
   and 4, what does each one report, and why is that the right behaviour for impact but would be
   wrong for trace?
2. `dlens trace` ran fine yesterday. Today you edited `models/marts/fct_orders.sql` and ran it
   again. Which check in `is_stale` makes it rebuild, and what would have happened if the cache
   rule only compared against `manifest.json`? Name one change that still would not trigger it.
3. `downstream`'s spec default is `include_indirect=True`, yet `dlens impact` and the agent's
   impact tool show direct edges only. What makes that true, and what does
   `test_traversal_calls.py` catch that the unit tests of `downstream` would not?
4. You upgrade dlens from 0.1.0 to 0.1.1 and the cache file is newer than every source file. Which
   check rebuilds it, and why isn't the mtime rule enough here? When would you bump
   `FORMAT_VERSION` rather than rely on the package version?
5. With `--include-indirect`, `raw.y` reaches `fct.total` by a JOIN and a GROUP_BY edge. How many
   paths does `upstream(fct.total, include_indirect=True)` return for raw.y, which hop does
   `downstream(raw.y, include_indirect=True).via` keep, and why does a depth limit of 2 cut
   `a → b (direct) → c (FILTER) → d (direct)` before `d`?

## Accessors added in v0.2
`model_info(uid)`, `model_ids()` and `exposure_info(uid)` expose the manifest facts the graph already stored (a node's `file`, `name`, `resource_type`; an exposure's `name`, `type`) so the agent tools never read private attributes. They return copies, or None for an unknown id.
