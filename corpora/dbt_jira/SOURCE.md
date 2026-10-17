# Source (set E, S06 / E4a)

- Upstream: https://github.com/fivetran/dbt_jira
- Tag: `v1.10.2`, pinned commit `0ed5dcf2e96b5ca138699825dcb605f61802406a` (2026-08-18)
- Vendored: 2026-10-17 (owner's set-E pick, 17 Oct 2026)
- Licence: Apache-2.0 (`LICENSE`, unmodified). Upstream ships no NOTICE file.

## Vendored dbt packages (`integration_tests/dbt_packages/`)
Installed once with `dbt deps` (dbt-core 1.12.5) and committed, so the project builds offline.
Versions are pinned in `integration_tests/package-lock.yml`. Each keeps its own upstream
`LICENSE`, and none ships a NOTICE file.

| Package | Version | Upstream | Licence |
|---|---|---|---|
| fivetran_utils | 0.4.13 | https://github.com/fivetran/dbt_fivetran_utils | Apache-2.0 |
| spark_utils | 0.3.3 | https://github.com/dbt-labs/spark-utils | Apache-2.0 |
| dbt_utils | 1.4.1 | https://github.com/dbt-labs/dbt-utils | Apache-2.0 |

`integration_tests/dbt_packages/jira` is the link that `dbt deps` makes for the package itself
(`packages.yml`: `local: ../`). dbt wrote it as an absolute symlink; it is committed as a
**relative** symlink to `../..`. Copy this directory with symlinks preserved (e.g.
`shutil.copytree(..., symlinks=True)`), or the copy recurses.

## Local changes (everything else is byte-for-byte upstream)
1. **Removed `docs/`**: the generated dbt docs site (3.7 MB of `index.html`, `manifest.json`,
   `catalog.json`). It isn't needed to build and holds another dbt version's artifacts.
2. **Added `integration_tests/profiles.yml`**: a DuckDB profile (`jira.duckdb`, schema
   `jira_integration_tests`, the schema the package's sources read via `var('jira_schema')`).
3. **Added the vendored packages and `integration_tests/package-lock.yml`** (above).
4. **`.gitignore`**: appended three negations so the packages, lock file and profile are tracked.
5. **`integration_tests/seeds/comment.csv`**: the `body` column of 128 of its 131 rows was cut to
   its first 1,000 characters. Upstream stress-tests long text with values up to 131,071
   characters, which made the file 16.8 MB; it is now 148 KB. Rows, columns, ids and every other
   value are unchanged, and the csv module re-quoted it (quote-minimal). Lineage depends only on
   the columns, so lineage is unaffected. Re-vendor from the pinned commit to restore the original.
6. **Removed CI and test scaffolding dbt never reads**: the package's `.github/`, and in each
   vendored package its CI config (`.circleci/`, `.buildkite/`, `.github/`) and its own
   `integration_tests/`. Those hold CI runner paths and sample profiles, nothing a build uses.
7. Added this `SOURCE.md`.

## Build
From `integration_tests/` (dbt-duckdb; no network once vendored):
`dbt build --empty --exclude resource_type:test --profiles-dir . && dbt docs generate --profiles-dir .`,
then `dlens ingest --artifacts target/`. Generated `target/`, `logs/` and `*.duckdb` are never
committed.

## Facts at this pin (S06 build, dbt-core 1.12.5 + dbt-duckdb 1.11.0)
- 61 enabled models, 0 disabled: 37 views, 11 tables, **13 ephemeral**. 61 − 13 ephemeral = the
  **48 materialised** models in Fivetran's docs. 18 of the 61 are `stg_*_tmp` views. There are 22
  seeds and 18 sources; each source is declared over its seed's table.
- No incremental models on DuckDB. The two models with an `is_incremental()` branch
  (`jira__daily_issue_field_history`, `int_jira__pivot_daily_field_history`) are configured as
  `'incremental' if jira_is_incremental_compatible() else 'table'`, so they build as `table`, and
  both compiled to the full-refresh (non-incremental) branch.
- Seven models read `current_date`/`current_timestamp` (the calendar spine and the models built
  on it). Lineage is unaffected; any future oracle run on this corpus must freeze the date.
