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

**Set E, fivetran/dbt_jira v1.10.2** (`corpora/dbt_jira`): built offline, 61 models (13
ephemeral), 1,046 columns, 761 direct and 4,830 indirect edges. Coverage: 60 FULL, 1 PARTIAL,
0 FAILED. The PARTIAL model is `int_jira__issue_sprint`. Its `field_history.*` comes from an
inlined ephemeral model whose body has its own `WITH`, and sqlglot doesn't expand the star
through that nested WITH: 8 gaps, a known engine limitation. Ingesting it also found that a
source declared over its seed's table claims the same relation; the source now wins (ingest.md).

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

## Package paths and citation coverage (S06b)

**What it does.** A model from a dbt package gets line-level citations in its own file, and
`dlens ingest --artifacts` / `dlens report` say how many citations are line-level and why the rest
are not.

**How it works.** dbt records `original_file_path` relative to the node's package, so a package
model's file on disk is `<packages-install-path>/<package>/<original_file_path>`.
`dlens.ingest.paths` turns (package, path) into that project-relative "display" path, reading
`packages-install-path` from `dbt_project.yml` (default `dbt_packages`). The engine reads the
source through it and stores the display path in `Edge.file` / `IndirectEdge.file`;
`LineageResult.files` carries it to the graph's model `file`. The chunker uses the same
`ProjectFiles`, so a chunk and a citation always name the same file (tested on all 61 dbt_jira
models). Root-project files keep their plain path, so graphs of projects without package models
are byte-identical to before (synthetic_shop, jaffle_shop checked against main).

Reads stay confined (`paths.resolve`, used by `safe_read` and so by the agent, validator and UI).
A path must resolve inside the project root, except that `dbt deps` installs a `local:` package as
a symlink that can point outside it (dbt_jira: `dbt_packages/jira -> ../..`). A path under
`<packages-install-path>/<pkg>/` that leaves the root is read only if (a) the graph or manifest
references it for that package and (b) the resolved package root's `dbt_project.yml` is named
`<pkg>`, and it must stay inside that root. A `dbt_packages/x -> $HOME` link reads nothing,
because in Ask mode file text can reach a cloud LLM.

`graph.citations.citation_coverage` counts citations the way users get them (columns and direct
edges through `Provenance`'s re-check; indirect edges by their flag) and groups the reasons.

**dbt 2.0.** The packages layout is **doc-verified, not run**: dbt's `packages-install-path`
reference gives the key and the `dbt_packages` default and draws no 2.0 distinction. No 2.0 build
with packages was run here (the S06 2.0.8 check used a project without packages).

**Why this design.** One resolver means the two features can't disagree on paths, and confinement
is written once. Storing the display path, not resolving at read time, keeps every reader (CLI,
agent, validator, UI, demo) unchanged: they already read `project_dir / file`. FORMAT_VERSION
stays at 4 because the JSON shape didn't change. Only the *value* of `file` for package models
did, from a path nothing could open. A new `builder_version` in the artifact cache's `meta.json`
(not in `graph.json`, so the demo bundle is untouched) rebuilds caches made before the fix.

**Alternatives rejected.** Resolving package paths at read time from `package_name`: every
reader would need the manifest or a new graph field. Following any symlink under
`dbt_packages/`: widens what can be read. Bumping FORMAT_VERSION: it changes the demo bundle's
contract for no shape change.

**Results (dbt_jira, 17 Oct 2026).**

| | before | after |
|---|---|---|
| SQL-model columns | 0 / 764 line-level | 613 / 764 (80.2%) |
| direct edges | 0 / 761 | 628 / 761 (82.5%) |
| indirect edges | 0 / 4830 | 3998 / 4830 (82.8%) |

282 seed/source columns cite a whole CSV/YAML file by design. Every model-level citation left
comes from SQL a macro writes. The 18 `stg_*_tmp` models are one
`fivetran_utils.union_connections(...)` call with no SELECT in the source (151 columns, 133
direct edges). 816 indirect edges have clause keys written by `dbt_utils.group_by(n)` or a
`{% for %}` loop, and 16 have clauses not found in the source. The ≥95% target was **not** met.
Closing the gap would need the engine to cite macro calls, which is outside S06b.

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
4. (S06b) dbt_jira's `dbt_packages/jira` is a symlink to `../..`. Walk through what `safe_read`
   does for `dbt_packages/jira/models/jira__issue_enhanced.sql`, for
   `dbt_packages/jira/integration_tests/profiles.yml`, and for the first path if `dbt_project.yml`
   up there were named `jira_fork`. Which check rejects each failing case?
5. (S06b) The fix changed `file` in graph.json for package models. Why is FORMAT_VERSION still 4,
   and what stops a cache built yesterday from being reused with the old, model-level citations?
   Why does that value live in `meta.json` and not in `graph.json`?
6. (S06b) After the fix, dbt_jira reports 82.5% of direct edges line-level and 60 FULL models.
   Explain why both numbers are true, which models hold the 133 model-level edges, and why
   citing their lines would need an engine change rather than a path fix.
