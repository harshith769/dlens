# Explain: artifact-only ingest (`src/dlens/ingest/target.py`, `graph/cache.py`; ADR 0013)

## What it does
`dlens ingest --artifacts TARGET_DIR` builds the lineage graph from a dbt `target/` directory
that already exists: `manifest.json` (required), `catalog.json` (optional) and the compiled SQL.
It never runs dbt, never connects to a warehouse and never opens a network connection. That is
how projects on Snowflake, BigQuery, Postgres, Redshift, Databricks, Spark or Trino get lineage,
and how the set-E public corpus is ingested without depending on our runtime.

It writes one folder, `TARGET_DIR/dlens/` (or `--out DIR`), with `graph.json` and `meta.json`.
`trace`, `impact` and `report` take `--artifacts TARGET_DIR` and read that graph. They never build
it: a missing or stale graph is an error that says to re-run ingest.

## How it works
1. **Version check** (`check_manifest_version`). The manifest's `metadata.dbt_schema_version`
   must be `v12`. That covers dbt 1.8 to 1.12 and dbt 2.0, verified on 1.12.5 and 2.0.8. Any other
   version raises `ArtifactError` with the version found and the supported list. The catalog
   must be `v1`. A field that moved between versions would otherwise parse as missing, silently.
2. **Dialect** (`resolve_dialect`). `metadata.adapter_type` maps to a sqlglot dialect: duckdb,
   snowflake, bigquery, postgres, redshift, databricks, spark, trino. `--dialect` overrides it. An
   unknown adapter is an error that tells the user to pass `--dialect`.
3. **Compiled SQL** (`_with_compiled_sql`). It comes from each model's `compiled_code`. When that is
   empty, it falls back to `target/compiled/<package>/<original_file_path>`. A model with neither is
   listed by ingest and ends up FAILED ("no compiled SQL"), so it never silently drops out.
4. **Schema.** With `catalog.json` it uses the same loaders as `dlens ingest PROJECT_DIR`.
   Without it, `catalog_from_manifest` builds a catalog from the YAML-declared columns (type
   `data_type` or `unknown`). Nodes that declare no columns stay unknown to sqlglot rather than
   look empty. The relation parts come from `relation_name`, so they match the relation map
   exactly.
5. **Lineage.** This is the same engine as for our corpora, so direct and indirect edges are built
   the same way. Catalog-less, `extract_lineage(..., grow_schema=True)` adds each parsed model's
   output columns to the schema for the models after it (spec §7 step 2). A `*` over a table
   nobody declared is a gap (TABLE_ONLY), never an edge. Ephemeral models resolve to their own
   columns (lineage.md, "Ephemeral models").
6. **Citations.** Source files are read from the target's parent when it holds `dbt_project.yml`.
   Otherwise edges cite whole files, and ingest says so.
7. **Cache** (`load_or_build_artifacts`). `meta.json` holds the sha256 of manifest.json and
   catalog.json, the resolved dialect, the dlens version and the graph format. The graph is reused
   only when all of them match; anything else, including an unreadable cache, rebuilds it.
8. **Summary** (`coverage_summary`). FULL = no gaps. PARTIAL = gaps, but at least one column edge
   into the model. TABLE_ONLY = no column edges, only DEPENDS_ON. FAILED = sqlglot raised. Every
   non-FULL model is listed with its gaps grouped by cause. The public `ParseQuality` enum is
   unchanged: PARTIAL and TABLE_ONLY here split its TABLE_ONLY.

## Why this design
- **Read artifacts, don't run dbt.** Running dbt needs the user's adapter, profile and
  credentials. The artifacts are already on disk after any `dbt compile`. Reading files only is
  also what makes the privacy promise checkable: no network code on this path.
- **Refuse unknown versions.** A wrong-version manifest parses fine with `extra="ignore"` and just
  loses fields. Failing loudly is better than a quietly worse graph.
- **The dialect comes from the manifest.** The user shouldn't have to know sqlglot's names. The
  adapter that compiled the SQL is the best evidence of its dialect.
- **Hash the inputs, not mtimes.** The artifacts are often copied (CI, a colleague's laptop), and
  copying changes mtimes, not content.
- **Catalog-less grows the schema.** YAML rarely declares every column. Without growth, the
  model after the first undeclared one can't resolve anything: on synthetic_shop, direct F1 0.48
  and indirect F1 0.11 without growth, against 1.0 / 1.0 with it.
- **Nothing written outside `target/dlens/`.** It's the user's repository. `target/` is already
  dbt's scratch space and is git-ignored in dbt projects.

## Alternatives rejected
- **Run `dbt compile` on the user's adapter**: needs credentials and their environment (ADR 0013).
- **Accept any manifest version and hope**: silent mis-parses (above).
- **Ask the user for the dialect**: an extra step that is usually redundant. It stays available
  as `--dialect`.
- **Cache keyed by mtime** (as the project-dir cache is): breaks on copied artifacts.
- **Read dbt 2.0's Parquet metadata (`target/info_schema/`) now**: out of S06 scope. dbt 2.0
  falls back to catalog-less until a later plan reads it. In the OSS 2.0.8 build,
  `dbt.node_columns.parquet` typed only seed columns, and `dbt.column_lineage.parquet` was empty:
  the static analysis engine that fills them is not part of the OSS distribution.

## Results (S06)
**Dialect round trip** (`scripts/dialect_check.py`, `eval/reports/s06_dialects.json`):
synthetic_shop's compiled SQL is transpiled from DuckDB to each dialect with sqlglot, and the
catalog types the same way. Relation names are rendered as each adapter writes them, and Snowflake
catalogs are upper-case. The fake artifacts are ingested and scored against `lineage_spec.yml`.

| Dialect | Direct F1 | Indirect F1 |
|---|---|---|
| duckdb (baseline) | 1.0000 | 1.0000 |
| snowflake | 0.9945 | 0.9968 |
| bigquery | 1.0000 | 1.0000 |
| postgres | 1.0000 | 1.0000 |

- **What it tests:** sqlglot's DuckDB → X round trip plus our dialect handling. It does **not**
  test real-world SQL written by hand for that warehouse.
- **Identifier case is the only normalisation in the comparison.** Column ids are lowercased
  (`column_id`, `short_id`), because Snowflake reports unquoted identifiers in upper case.
  Nothing else is rewritten, matched loosely or ignored.
- **Postgres** first scored indirect F1 0.9589. Postgres has no QUALIFY, so sqlglot rewrites it
  as a subquery plus `WHERE _w = 1`, and the window's keys were lost. The fix is a general rule
  (ADR 0020, S06 clarification): a FILTER or JOIN key computed by a window in an inner query
  resolves to the window's PARTITION BY / ORDER BY columns plus its value arguments. The same
  rule covers hand-written `where rn = 1` dedupes.
- **Snowflake: equivalent SQL, different labels (accepted).** `count(x) filter (where c)` and
  `count(iff(c, x, null))` (what sqlglot writes for Snowflake) mean the same thing. Under the ADR
  0020 rules, `c` gets a CONDITIONAL indirect edge in the first form and a direct edge in the
  second, because an IFF/CASE condition decides the value. That accounts for all 4 Snowflake
  differences. No rule changes in S06.

**Catalog-less coverage on synthetic_shop**: 49 FULL, 0 PARTIAL, 0 TABLE_ONLY, 0 FAILED.
Direct and indirect F1 are 1.0 / 1.0, the same as with a catalog. That is because synthetic_shop
declares every seed column in YAML; most real projects don't. On the eph_shop fixture, whose
seeds are undeclared, `customer_orders` is PARTIAL: its 3 columns that come through `select *
from raw_orders` are gaps.

**CI** (`core-artifacts` job): a core install with no extras on macos-latest and windows-latest
runs `dlens ingest --artifacts` on the committed eph_shop fixture (build, cache reuse, trace,
catalog-less with `--out`) plus the artifact-ingest unit tests. Its first Windows run found a real
bug: piped output on Windows is cp1252, and `trace`'s tree characters crashed it. The CLI now
switches a non-UTF-8 stdout/stderr to UTF-8 at start (`cli.use_utf8`). Every `uv sync` step in CI has one
retry after 15 s for transient download errors. The retry also re-runs a real resolution error
once. That is acceptable: the second attempt fails the same way and still fails the job, so it
costs 15 s and hides nothing.

**Absolute paths**: `scripts/make_artifact_fixture.py` drops `root_path` and relativises any
string holding the build directory. `tests/unit/test_no_absolute_paths.py` scans the committed
fixtures, demo, docs, eval and corpora. Known-safe mentions pass only through an exact
(file, substring) allowlist.

## Explain-back questions
1. A colleague runs `dlens ingest --artifacts target/` on artifacts from dbt 1.7, then on a
   copy of the same `target/` on another laptop. What happens in each case, and which two values
   in `meta.json` decide whether the second machine reuses a cached graph?
2. Without `catalog.json`, why does `customer_summary` in eph_shop still get HIGH-confidence
   edges while `customer_orders` is PARTIAL? Name the function that makes the difference and
   say what it adds to the schema, and when.
3. On Postgres, why did every QUALIFY FILTER edge disappear before S06, and why does
   `count(x) filter (where c)` on Snowflake now give a direct edge from `c` instead of a
   CONDITIONAL one? Which of the two did we fix, and why not the other?
