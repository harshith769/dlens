# Explain: lineage graph and CLI (`src/dlens/graph/`)

## What it does
`build_graph(project_dir)` runs ingest and `extract_lineage`, then wraps the result in a
`LineageGraph`. The graph answers two questions:
- `upstream(col)`: every path from `col` back to the columns it comes from (`list[LineagePath]`,
  each path a chain of `Edge`s with kind, expression, file and lines).
- `downstream(col)`: an `ImpactResult` with affected columns by depth, the edge that reached each
  one, affected models, affected exposures (through CONSUMES) and a `truncated` flag.

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
5. **`include_indirect`** is accepted on both calls and does nothing in v0.1: there are no
   indirect edges yet. `deferred_indirect` is only stored and saved, so v0.3 can promote it.
6. **`resolve`**: an exact id wins. Otherwise a query with a dot matches ids ending in
   `"." + query`, so `stg_orders.order_id` can't match `xstg_orders.order_id`. Several matches raise
   `AmbiguousColumn` listing the full ids. No match raises `ColumnNotFound` with the 3 closest
   short ids (`difflib`). Bare column names are rejected on purpose.
7. **Save** writes `json.dumps(indent=2, sort_keys=True)`, nodes sorted by id, edges by
   `(from, to)`, plus `version`. The same graph always gives the same bytes, so it diffs cleanly.
   `__eq__` compares that canonical dict, which is what the round-trip tests use.
8. **Cache** (`cache.py`): `target/dlens_graph.json` is used unless it is missing, older than
   `target/manifest.json`, or older than any file under `models/`, `seeds/`, `macros/`,
   `snapshots/`, `tests/` or `dbt_project.yml`. `--rebuild` forces a rebuild, which re-runs dbt.
9. **Rendering** (`render.py`) merges paths that share a prefix, so each hop prints once. A hop
   shows the column, `[KIND]`, the expression (cut at 60 characters) and `file:lines`.
   Names are `model.column`, or the full id if two columns share that short form.

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
3. `include_indirect=True` is the default for `downstream` but changes nothing in v0.1. Why does
   the graph still save `deferred_indirect`, and what has to be added in v0.3 so that an indirect
   (window key) dependency shows up in `impact`?
