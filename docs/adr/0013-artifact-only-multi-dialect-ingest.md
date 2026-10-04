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
