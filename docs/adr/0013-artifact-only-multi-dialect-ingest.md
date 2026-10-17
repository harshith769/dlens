# 0013. Artifact-only, multi-dialect ingest with catalog-less fallback

- Status: Accepted
- Date: 2026-10-04
- Source: docs/DLENS_SPEC.md, Section 0, row 23
- Implemented in: S06 (E1)

## Context

Ingest runs `dbt compile` with dbt-duckdb. Real users are on Snowflake, BigQuery, Postgres, Databricks or Redshift and already have `target/` artifacts. The set-E public corpus also needs a path that doesn't depend on our runtime.

## Decision

`dlens ingest --artifacts <target/>` reads `manifest.json`, `catalog.json` and compiled SQL; the sqlglot dialect comes from the manifest's `adapter_type`. No dbt run, no credentials. Without `catalog.json`, a catalog-less fallback uses manifest-declared columns and marks star expansion TABLE_ONLY, clearly reported. dbt-duckdb stays the build runtime for our own corpora.

## Consequences

- Scope stays dbt-only; no warehouse access.
- Tests transpile corpus SQL to snowflake/bigquery/postgres and require edge F1 within 0.02 of DuckDB.
- The "always with a catalog schema" rule gains one documented, flagged exception.

## Alternatives rejected

- Run `dbt compile` on the user's adapter: needs credentials and their environment.
- DuckDB dialect only: excludes most real users.

## Clarification (S06, 17 Oct 2026)

The CLI surface, as implemented and approved by the owner (S06 plan Q4):

- `dlens ingest [PROJECT_DIR] [--artifacts TARGET_DIR] [--dialect X] [--out DIR] [--rebuild]`.
  Exactly one of PROJECT_DIR and `--artifacts` is given. `dlens ingest PROJECT_DIR` is unchanged
  (DLens runs dbt-duckdb; its output is checked against main). `--dialect`, `--out` and
  `--rebuild` apply to `--artifacts` only.
- `--artifacts` writes `graph.json` and `meta.json` (manifest/catalog sha256, dialect, dlens
  version, format) to `<TARGET_DIR>/dlens/`, or to `--out`, and nowhere else. The graph is reused
  while `meta.json` matches.
- `trace`, `impact` and `report` gain `--artifacts TARGET_DIR`. They read that graph and never
  build it; a missing or stale graph is an error that says to re-run `dlens ingest --artifacts`.
  `ask` and `ui` get this in E2 (S14).
- Supported: manifest v12 (dbt 1.8 to 1.12 and 2.0; verified on 1.12.5 and 2.0.8), catalog v1.
  Adapters map to sqlglot dialects: duckdb, snowflake, bigquery, postgres, redshift, databricks,
  spark, trino. Anything else is an error that names `--dialect`.
- dbt 2.0 writes no `catalog.json` (its column metadata is Parquet under `target/info_schema/`), so
  2.0 targets use the catalog-less fallback until a later plan reads that format.
- The spec §7 `build_graph` signature is unchanged. `build_graph_from_artifacts` and
  `load_or_build_artifacts` are additive.
