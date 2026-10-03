# Explain: ingest (`src/dlens/ingest/`)

## What it does
Given a dbt project directory, it runs dbt, reads the artifacts, and hands the lineage
engine three things: compiled SQL per model, a sqlglot schema, and a map from warehouse
relation names to dbt `unique_id`s. `dlens ingest PROJECT_DIR` prints a summary.

## How it works
1. `runner.py` finds `dbt` next to the running interpreter (else on PATH), then runs
   `dbt build --empty --exclude resource_type:test` and `dbt docs generate`.
   Failures raise `DbtError` with the command and the last 20 output lines.
2. `artifacts.py` loads `manifest.json` / `catalog.json` into Pydantic models that keep
   only the needed fields (unknown fields ignored; tests and other node types dropped;
   catalog columns sorted by `index`).
3. `schema.py` builds `{db: {schema: {table: {col: type}}}}` from the catalog, builds
   `normalised relation_name -> unique_id` from the manifest, and lists catalog relations
   that no manifest node claims.

## Why these choices
- **Compiled SQL only.** Raw model SQL contains Jinja (`ref`, macros) that sqlglot cannot
  parse; dbt already resolved it in `target/compiled`.
- **`build --empty`.** Tested on jaffle_shop: catalog identical to a full `dbt build`
  (8 tables, same names, types, order). Tables must exist for `docs generate` to report
  column types; `--empty` builds them with zero rows, so ingest is fast and data-independent.
  Tests are excluded (they check data, not lineage). `docs generate` adds the
  catalog and recompiles. The recompile matters: under `--empty`, dbt compiles every `ref` as
  `(select * from x where false limit 0)`, which adds a fake `SELECT *` hop to every lineage
  path. An earlier version passed `--no-compile` and kept those wrappers in `target/compiled`.
  Spec §7 step 1 was updated to match.
- **Catalog schema.** sqlglot needs column lists to expand `SELECT *` and resolve unqualified
  columns; the warehouse is the ground truth for those, not inference from SQL.
- **Relation map.** Compiled SQL refers to tables by name (`"db"."main"."orders"`), the graph
  uses `unique_id`. Everything is lowercased and quotes stripped, because DuckDB is
  case-insensitive and artifacts quote differently. Two nodes colliding after normalising
  raises instead of silently overwriting. Unmapped catalog relations are reported, not hidden:
  each is a table the lineage engine could not attribute to a node.
- Ephemeral models have no `relation_name`, so they are not in the map.

## Alternatives rejected
- Parsing raw SQL after rendering Jinja ourselves: re-implements dbt, and gets it wrong.
- Inferring the schema from SQL / `dbt compile` alone: no real tables, no column types.
- Matching relations by bare table name: breaks on same name in two schemas.
- `uv run dbt` from inside the package: nests uv, and may pick a different environment.
- Full `dbt build`: same catalog, slower, depends on data volume.

## Explain-back questions
1. Why does `docs generate` need `build` to have run first, and what would the catalog
   contain if we only ran `dbt compile`?
2. Why lowercase schema keys and the relation map, and what is the failure mode that the
   collision check guards against?
3. A catalog relation shows up as "unmapped". Name two possible causes and what that means
   for lineage on models that read from it.
