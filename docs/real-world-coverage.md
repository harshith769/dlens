# Real-world parse coverage (S14, v0.3 E4b)

How well DLens's lineage holds up on public dbt projects it was not built against. These are
**measurements, not gold**: no questions or gold were created from any of these projects, and
nothing from them is committed. DLens 0.2.0 (sqlglot 30.21.0), dbt-core 1.12.5 + dbt-duckdb
1.11.0, measured 24 Oct 2026.

Projects come from
[awesome-public-dbt-projects](https://github.com/InfuseAI/awesome-public-dbt-projects), plus
fivetran/dbt_jira (set E, explicitly allowed). The selection criteria were: a licence that
allows it, buildable on DuckDB (or artifacts producible in a scratch dir), and ≤ 300 models.
Excluded: Datadex (no dbt project at the current commit), SOMA (no licence file), and the
Snowflake/BigQuery projects (GitLab, Mattermost, Spellbook, Cal-ITP, …: warehouse-only and/or far
above 300 models).

## Projects

| Project | Repo @ pinned commit | Licence | Dialect | Models | Columns | dbt artifacts |
|---|---|---|---|---:|---:|---|
| jaffle_shop | [dbt-labs/jaffle_shop](https://github.com/dbt-labs/jaffle_shop) @ `fd7bfacae4f497ff044a6a0275268676bf1b64c3` | Apache-2.0 | duckdb | 5 | 38 | full catalog |
| tw_campaign_finance | [g0v/tw_campaign_finance](https://github.com/g0v/tw_campaign_finance) @ `042c5f7c5431ada52830eaf01dce0fbada65322d` | MIT | duckdb | 4 | 25 | partial catalog (1 model reads a downloaded CSV not in the repo) |
| danish-democracy-data | [bgarcevic/danish-democracy-data](https://github.com/bgarcevic/danish-democracy-data) @ `a11ecd4dce56ac34156fbc4515d6c0a659e47b2f` | MIT | duckdb | 26 | 401 | partial catalog (the 18 raw API sources are extracted by a script, not in the repo) |
| nba-monte-carlo | [matsonj/nba-monte-carlo](https://github.com/matsonj/nba-monte-carlo) @ `e8bf34f252923a640ad224d24e49f007684016ba` | MIT | duckdb | 68 | 572 | partial catalog (raw CSV/parquet loaded by dlt, not in the repo); `target-path: ../docs` |
| dbt_jira (set E) | [fivetran/dbt_jira](https://github.com/fivetran/dbt_jira) v1.10.2 @ `0ed5dcf2e96b5ca138699825dcb605f61802406a` | Apache-2.0 | duckdb | 61 | 1046 | full catalog (integration-test seeds) |

"Models" counts dbt models only (no seeds or sources). "Columns" is every column in the graph,
seeds and sources included.

## Parse quality

The levels are the ones `dlens ingest` prints. FULL means column lineage with no gaps; PARTIAL
means gaps, but at least one column edge into the model; TABLE_ONLY means only model-level
dependencies; FAILED means the SQL could not be parsed. PARTIAL and TABLE_ONLY split the
engine's TABLE_ONLY.

| Project | FULL | PARTIAL | TABLE_ONLY | FAILED | Ingest time |
|---|---:|---:|---:|---:|---:|
| jaffle_shop | 5 (100%) | 0 | 0 | 0 | 0.5 s |
| tw_campaign_finance | 3 (75.0%) | 0 | 1 (25.0%) | 0 | 0.4 s |
| danish-democracy-data | 21 (80.8%) | 0 | 5 (19.2%) | 0 | 0.7 s |
| nba-monte-carlo | 42 (61.8%) | 12 (17.6%) | 9 (13.2%) | 5 (7.4%) | 1.3 s |
| dbt_jira | 60 (98.4%) | 1 (1.6%) | 0 | 0 | 3.1 s |

Ingest time is the wall time of `dlens ingest --artifacts … --rebuild` (graph built from
scratch, including interpreter start-up) on a laptop CPU (WSL2).

**Catalog-less fallback** (same artifacts with `catalog.json` removed), for the three projects
whose catalog is partial:

| Project | FULL | PARTIAL | TABLE_ONLY | FAILED |
|---|---:|---:|---:|---:|
| tw_campaign_finance | 0 | 1 | 3 | 0 |
| danish-democracy-data | 25 (96.2%) | 1 | 0 | 0 |
| nba-monte-carlo | 47 (69.1%) | 8 | 7 | 6 |

## Top failing constructs

| Construct | Where | Count | Cause |
|---|---|---:|---|
| `select *` over a relation the catalog doesn't have (`unexpanded *`) | danish (5 models), nba (13 models), dbt_jira (`int_jira__issue_sprint`) | 19 models | The relation was not built (its raw data is not in the repo), so the catalog has no columns for it. Expected; the gap is reported. |
| **dbt Python models** parsed as SQL (`ParseError` at `import pandas as pd`) | nba: `nba_elo_rollforward`, `nba_tiebreakers_optimized`, `nfl_elo_rollforward`, `nfl_tiebreakers_optimized` | 4 models | **DLens gap**: a `.py` model has no SQL to parse. It should be reported as "Python model: model-level lineage only", not as FAILED. Carry-forward (lineage code is out of S14 scope). |
| `UNION ALL` whose second branch is `select *` from an unknown relation | nba: `initialize_seeding` | 1 model | **sqlglot**: `lineage()` raises for the second column but not the first. Minimal reproduction: [`docs/upstream/0001-sqlglot-lineage-union-star-index.md`](upstream/0001-sqlglot-lineage-union-star-index.md). |
| Columns of a model that reads a file (`read_csv(...)`) not in the catalog (`unresolved column`) | tw: `stg_transaction` (×26); nba: `nba_raw_schedule`, `nfl_raw_*` | 5 models | No schema for a file read without a built relation. Expected. |
| Table not in the manifest | nba (5 models) | 5 models | The models read relations created outside dbt (dlt-loaded tables, a `random_num_gen` helper). Expected. |
| `Unknown column: game_id` (catalog-less only) | nba: `nba_elo_history`, `reg_season_actuals_enriched` | 2 models | The column comes from a Python model, so neither YAML nor parsed SQL declares it. Expected under the fallback. |

## Findings for DLens (carry-forward, not fixed in S14)
1. **Python models** should get a clear "Python model: no SQL lineage" level or reason, not a
   ParseError counted as FAILED.
2. **A partial catalog does worse than none** on danish-democracy-data (21 vs 25 FULL). When a
   relation is missing from `catalog.json`, DLens does not fall back to the YAML-declared
   columns, as it does with no catalog at all. A per-relation fallback would recover these
   models.
3. **`target-path` outside the project** (nba-monte-carlo writes to `../docs`): ingest works,
   but every edge cites a whole file, because no dbt project sits around the target. Passing the
   project folder explicitly (as `dlens ui --project … --artifacts …` already does) would allow
   line citations.
4. Citations were 100% line-level on jaffle_shop, tw_campaign_finance and danish; on dbt_jira
   about 80% are line-level (macro-built SELECTs cite the whole file, as documented).

## Reproduce
For each project, in a scratch directory (nothing here is committed):

```bash
git clone https://github.com/<owner>/<repo>.git && cd <repo>
git checkout <pinned commit>
cd <dbt project folder>     # jaffle_shop, tw_campaign_finance: .   danish: dbt   nba: transform
# a scratch DuckDB profile (the projects' own profiles point at paths outside the repo):
mkdir -p ../e4b-profiles && cat > ../e4b-profiles/profiles.yml <<'YML'
<profile name from dbt_project.yml>:
  target: dev
  outputs:
    dev: {type: duckdb, path: e4b.duckdb, threads: 4, extensions: [httpfs, parquet]}
YML
dbt deps --profiles-dir ../e4b-profiles
dbt build --empty --profiles-dir ../e4b-profiles   # fails on models whose raw data is absent
dbt compile --profiles-dir ../e4b-profiles         # compiled SQL for every model
dbt docs generate --profiles-dir ../e4b-profiles   # catalog.json for what was built
time dlens ingest --artifacts target --rebuild     # nba-monte-carlo: --artifacts ../docs
dlens report --json --artifacts target             # per-model reasons
# catalog-less fallback: copy target/ elsewhere, delete catalog.json, ingest that copy
```

dbt_jira builds offline from the vendored corpus (`corpora/dbt_jira`, see its `SOURCE.md`):
`dbt build --empty` and `dbt docs generate` in `integration_tests/`, then
`dlens ingest --artifacts integration_tests/target`.
