# DLens

GPS for your data: trace any dbt column to its source, see what breaks before you change it, with
the file and line for every step.

[![CI](https://github.com/harshith769/dlens/actions/workflows/ci.yml/badge.svg)](https://github.com/harshith769/dlens/actions/workflows/ci.yml)
[![PyPI](https://img.shields.io/pypi/v/dlens-lineage)](https://pypi.org/project/dlens-lineage/)
[![Licence](https://img.shields.io/badge/licence-Apache--2.0-blue)](https://github.com/harshith769/dlens/blob/main/LICENSE)

DLens reads a dbt project, parses the *compiled* SQL with [sqlglot](https://github.com/tobymao/sqlglot)
against the real warehouse schema, and builds a column-level lineage graph. Every edge records how a
column is derived (rename, transformation, aggregation, ...), the expression, and where in the model
file it lives.

## Status

**v0.1.0: lineage CLI.** It works on DuckDB dbt projects (dbt-core 1.12, dbt-duckdb 1.11), Python
3.12 and 3.13. The Q&A agent and the benchmark are not built yet: see the [roadmap](#roadmap).

## Quickstart

```bash
pip install dlens-lineage
git clone --depth 1 https://github.com/harshith769/dlens.git   # for the example projects
cd dlens

dlens ingest corpora/jaffle_shop                      # runs dbt, shows what DLens will see
dlens trace customers.customer_lifetime_value -p corpora/jaffle_shop
dlens impact stg_orders.order_id -p corpora/jaffle_shop
dlens report -p corpora/jaffle_shop                   # parse quality per model
```

Use your own project the same way: `dlens ingest path/to/dbt_project` (DuckDB profile in the project
directory). `ingest` runs dbt, so it needs the project's seeds and sources to be buildable. The first
run takes about 10 seconds on jaffle_shop; after that the graph is cached in
`target/dlens_graph.json` and rebuilt when the manifest, your SQL, or the DLens version changes
(`--rebuild` forces it). Column ids are `model.column`.

### Example output

The commands below ran on [`corpora/synthetic_shop`](https://github.com/harshith769/dlens/blob/main/corpora/synthetic_shop/DESIGN.md), a
15-model project built to contain traps (renames, CASE, multi-hop joins, aggregates). Paths are
relative to the project; long lines are real, not wrapped.

`dlens ingest corpora/synthetic_shop`

```text
models:      15
seeds:       6
sources:     0
exposures:   0
columns:     132
unmapped relations: 0
```

`dlens trace fct_orders.revenue_finance -p corpora/synthetic_shop`

```text
fct_orders.revenue_finance
├─ int_customer_order_history.items_subtotal  [TRANSFORMATION]  int_customer_order_history.items_subtotal - int_customer_or…  models/marts/fct_orders.sql:13-13
│  └─ int_order_financials.items_subtotal  [IDENTITY]  int_order_financials.items_subtotal AS items_subtotal  models/intermediate/int_customer_order_history.sql:2-2
│     └─ int_orders_enriched.items_subtotal  [IDENTITY]  orders.items_subtotal AS items_subtotal  models/intermediate/int_order_financials.sql:23-23
│        └─ int_order_items_enriched.line_amount  [AGGREGATION]  COALESCE(item_agg.items_subtotal, 0) AS items_subtotal <- S…  models/intermediate/int_orders_enriched.sql:24-24
│           ├─ stg_order_items.quantity  [TRANSFORMATION]  items.quantity * items.unit_price AS line_amount  models/intermediate/int_order_items_enriched.sql:8-8
│           │  └─ raw_order_items.quantity  [IDENTITY]  raw_order_items.quantity AS quantity  models/staging/stg_order_items.sql:5-5
│           └─ stg_order_items.unit_price  [TRANSFORMATION]  items.quantity * items.unit_price AS line_amount  models/intermediate/int_order_items_enriched.sql:8-8
│              └─ raw_order_items.unit_price  [IDENTITY]  raw_order_items.unit_price AS unit_price  models/staging/stg_order_items.sql:6-6
└─ int_customer_order_history.refund_amount  [TRANSFORMATION]  int_customer_order_history.items_subtotal - int_customer_or…  models/marts/fct_orders.sql:13-13
   └─ int_order_financials.refund_amount  [IDENTITY]  int_order_financials.refund_amount AS refund_amount  models/intermediate/int_customer_order_history.sql:2-2
      └─ stg_refunds.refund_amt  [AGGREGATION]  COALESCE(refunds_per_order.refund_amount, 0) AS refund_amou…  models/intermediate/int_order_financials.sql:26-26
         └─ raw_refunds.refund_amt  [IDENTITY]  raw_refunds.refund_amt AS refund_amt  models/staging/stg_refunds.sql:4-4

3 path(s), deepest 6 hop(s), 3 origin column(s)
```

`dlens impact raw_orders.tax_usd -p corpora/synthetic_shop`

```text
raw_orders.tax_usd
└─ stg_orders.tax_amount  [RENAME]  raw_orders.tax_usd AS tax_amount  models/staging/stg_orders.sql:6-6
   └─ int_orders_enriched.order_tax  [RENAME]  orders.tax_amount AS order_tax  models/intermediate/int_orders_enriched.sql:22-22
      ├─ int_order_financials.order_total  [TRANSFORMATION]  orders.items_subtotal + orders.order_tax AS order_total  models/intermediate/int_order_financials.sql:25-25
      │  └─ int_customer_order_history.order_total  [IDENTITY]  int_order_financials.order_total AS order_total  models/intermediate/int_customer_order_history.sql:2-2
      │     └─ fct_orders.order_total  [IDENTITY]  int_customer_order_history.order_total AS order_total  models/marts/fct_orders.sql:10-10
      └─ int_order_financials.sales_tax  [RENAME]  orders.order_tax AS sales_tax  models/intermediate/int_order_financials.sql:24-24
         └─ int_customer_order_history.sales_tax  [IDENTITY]  int_order_financials.sales_tax AS sales_tax  models/intermediate/int_customer_order_history.sql:2-2
            ├─ fct_orders.revenue_marketing  [TRANSFORMATION]  int_customer_order_history.items_subtotal + int_customer_or…  models/marts/fct_orders.sql:14-14
            │  └─ fct_daily_revenue.revenue_marketing  [AGGREGATION]  SUM(fct_orders.revenue_marketing) AS revenue_marketing  models/marts/fct_daily_revenue.sql:5-5
            └─ fct_orders.sales_tax  [IDENTITY]  int_customer_order_history.sales_tax AS sales_tax  models/marts/fct_orders.sql:9-9
               └─ dim_customers.lifetime_value  [AGGREGATION]  COALESCE(order_agg.lifetime_value, 0) AS lifetime_value <- …  models/marts/dim_customers.sql:21-21

11 affected column(s), 7 model(s)
  depth 1: 1 column(s)
  depth 2: 1 column(s)
  depth 3: 2 column(s)
  depth 4: 2 column(s)
  depth 5: 3 column(s)
  depth 6: 2 column(s)
models: dim_customers, fct_daily_revenue, fct_orders, int_customer_order_history, int_order_financials, int_orders_enriched, stg_orders
exposures: none
```

`dlens report -p corpora/synthetic_shop`

```text
Parse quality per model:
  dim_customers               FULL
  fct_daily_revenue           FULL
  fct_orders                  FULL
  fct_payment_events          FULL
  int_customer_order_history  FULL
  int_order_financials        FULL
  int_order_items_enriched    FULL
  int_orders_enriched         FULL
  int_payment_events          FULL
  stg_customers               FULL
  stg_order_items             FULL
  stg_orders                  FULL
  stg_payments                FULL
  stg_products                FULL
  stg_refunds                 FULL

Models: 15 FULL, 0 TABLE_ONLY, 0 FAILED
Edges: 115  (AGGREGATION 14, IDENTITY 58, RENAME 22, TRANSFORMATION 21)
Model-level citations: 0
Low-confidence edges: 0
Deferred indirect (window keys, v0.3): 2
Constant columns (no edges): 0
```

## Support matrix

DLens is tested construct by construct against golden files. The table, including what is partial,
unsupported and untested, is in the
[construct support matrix](https://github.com/harshith769/dlens/blob/main/docs/explain/lineage.md#construct-support).

## How it works

```text
 dbt project ──dbt build --empty + docs generate──▶ manifest.json + catalog.json + target/compiled/*.sql
                                                   │
                       catalog columns ──▶ sqlglot schema (every parse is schema-aware)
                                                   │
        compiled SQL (one model) ──sqlglot lineage──▶ column edges + kind + file:lines
                                                   │
                         LineageGraph (NetworkX) ◀─┘──▶ target/dlens_graph.json (cache)
                                  │
                    dlens trace · dlens impact · dlens report
```

Design notes for each part are in [`docs/explain/`](https://github.com/harshith769/dlens/blob/main/docs/explain/lineage.md).

## Roadmap

- **v0.1** (this release): lineage CLI.
- **v0.2**: a Q&A agent that answers lineage questions by calling these graph tools; every claim
  carries a file/line citation checked by a validator.
- **v0.3**: hybrid retrieval (graph + RAG) and window/join-key (indirect) edges.
- **v1.0**: a published benchmark against vector-only RAG, with design-authored gold labels.

## Limitations

- DuckDB only. Other warehouses may work through sqlglot dialects but are untested.
- Python 3.12 and 3.13 only; dbt-core is pinned to 1.12.x and dbt-duckdb to 1.11.x.
- `ingest` runs dbt in the project directory (it writes `target/` and `logs/`).
- Only *value* dependencies are edges. Join, filter, GROUP BY and window keys are not edges yet
  (window keys are recorded as deferred).
- Some constructs are partial or unsupported; `SELECT *` over a join with duplicate column names is
  untested. See the [support matrix](https://github.com/harshith769/dlens/blob/main/docs/explain/lineage.md#construct-support).
- Jinja is handled by dbt, not by DLens: DLens only parses the compiled SQL. If dbt cannot build
  the project, `dlens ingest` fails with dbt's error.
- Diff (comparing the lineage of two columns, e.g. two revenue definitions) is planned for v1.x;
  comparing two versions of a project is out of scope.
- Pre-1.0: the CLI output and the Python API may change between minor versions.

## Credits

[sqlglot](https://github.com/tobymao/sqlglot) does the SQL parsing and scope analysis.
[dbt](https://github.com/dbt-labs/dbt-core) and [dbt-duckdb](https://github.com/duckdb/dbt-duckdb)
produce the manifest, catalog and compiled SQL.
[jaffle_shop](https://github.com/dbt-labs/jaffle_shop_duckdb) is vendored as an example corpus.
[dbt-colibri](https://github.com/b-ned/dbt-colibri) is prior art for dbt column lineage and the
comparison point for the v1.0 benchmark.

## Contributing

See [CONTRIBUTING.md](https://github.com/harshith769/dlens/blob/main/CONTRIBUTING.md). Changes are listed in [CHANGELOG.md](https://github.com/harshith769/dlens/blob/main/CHANGELOG.md).

## Licence

Apache-2.0. See [LICENSE](https://github.com/harshith769/dlens/blob/main/LICENSE). The vendored jaffle_shop keeps its own licence in
[`corpora/jaffle_shop/LICENSE`](https://github.com/harshith769/dlens/blob/main/corpora/jaffle_shop/LICENSE).
