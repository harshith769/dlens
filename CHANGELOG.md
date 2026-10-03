# Changelog

All notable changes to this project are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and the project uses
[Semantic Versioning](https://semver.org/) (pre-1.0: minor versions may change behaviour).

## [0.1.0] - 2026-10-03

First public release: the lineage CLI.

### Added
- `dlens ingest`: runs dbt (build `--empty`, docs generate) and reads the manifest, catalog and
  compiled SQL into a schema-aware ingest result.
- Column-level lineage engine on sqlglot: direct edges with a kind (IDENTITY, RENAME,
  TRANSFORMATION, AGGREGATION), the expression, file and line range, plus parse quality per model.
- `LineageGraph` with upstream paths and downstream impact (columns, models, exposures).
- `dlens trace`, `dlens impact` and `dlens report` (`--json`).
- Graph cache at `target/dlens_graph.json`, rebuilt when the manifest or project sources change,
  or when the cache-format version or the DLens version differs.
- Golden tests per SQL construct and a generated construct support matrix
  (`docs/explain/lineage.md`), including untested gaps.
- Vendored example corpora: `jaffle_shop` and the trap-laden `synthetic_shop`.

### Known limitations
- DuckDB only; Python 3.12 and 3.13; dbt-core 1.12.x, dbt-duckdb 1.11.x.
- Only value dependencies are edges; join/filter/group/window keys are deferred.
- `SELECT *` over a join with duplicate column names is untested.

[0.1.0]: https://github.com/harshith769/dlens/releases/tag/v0.1.0
