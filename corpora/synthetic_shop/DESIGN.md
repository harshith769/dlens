# synthetic_shop: corpus design (v0.1, Phase A)

A small online shop with customers, orders, order items, products, payments and refunds. It is a dbt
project on DuckDB and the primary DLens benchmark corpus (spec §10). In v0.1 it has **6 seeds and
exactly 15 models** in three layers. It grows to 40–60 models in v0.3.

This document is the **source of truth** for `lineage_spec.yml` (spec §11.1). The gold spec is written
from the rules below and never from parser output. The Phase B SQL must implement these rules exactly.
If the SQL and this document disagree, the SQL is wrong.

Status: Phase A (design only). No SQL, seeds CSVs or `dbt_project.yml` yet.

## Conventions

- **Column ids** are `model.column`. Seed columns (`raw_*`) are leaves: they appear only as `from`.
- **Direct edges (phase v0.1)** link an output column to every upstream column whose *value* flows
  into it. There are four kinds:
  - `IDENTITY`: the bare column with the same name.
  - `RENAME`: the bare column under a different name.
  - `TRANSFORMATION`: a non-aggregate expression (arithmetic, CASE, string functions, a non-aggregate window function).
  - `AGGREGATION`: the value passes through an aggregate function (sum, min, max, count) and the grain changes.
- **Strongest-kind rule.** Some columns are computed in several steps inside one model (in a CTE, then
  finished in the outer SELECT). The edge kind is then the strongest operation on the path inside that
  model, ordered `AGGREGATION > TRANSFORMATION > RENAME > IDENTITY`. For example,
  `coalesce(agg.items_subtotal, 0)`, where `agg.items_subtotal = sum(line_amount)`, is AGGREGATION.
  `lag(order_date) over (...)` is TRANSFORMATION.
- **UNION ALL** gives one edge per branch into each output column. Output names come from the first
  branch.
- **`SELECT *`** gives one IDENTITY edge per expanded column (the catalog schema expands the star).
- **Not direct edges:** columns that appear only in JOIN ON, GROUP BY, WHERE, or a window's
  PARTITION BY / ORDER BY. These are phase v0.3 indirect edges, listed under
  [Deferred indirect edges](#deferred-indirect-edges).
- **Literals.** No output column may be a pure literal, because every model column must have at
  least one incoming edge.

## Seeds (6 seeds, 30 columns)

Raw exports with source-system names (`id`, `user_id`, `amt`, `method`). Staging renames them.

| Seed | Grain | Columns |
|---|---|---|
| `raw_customers` | one row per customer | `id`, `first_name`, `last_name`, `email`, `country`, `created_at` |
| `raw_orders` | one row per order | `id`, `user_id`, `order_date`, `status`, `tax_usd` |
| `raw_order_items` | one row per order line | `id`, `order_id`, `product_id`, `quantity`, `unit_price` |
| `raw_products` | one row per product | `id`, `name`, `category`, `list_price` |
| `raw_payments` | one row per payment | `id`, `order_id`, `method`, `amt`, `created_at` |
| `raw_refunds` | one row per refund | `id`, `order_id`, `refund_amt`, `reason`, `created_at` |

Value domains for the Phase B data generator:
- `raw_orders.status` takes the values `placed`, `shipped`, `completed`, `return_pending` and `returned`.
- An order can have 0..n payments and 0..n refunds.
- `unit_price` is sometimes below `list_price`.

## Staging (6 models, 30 columns)

One model per seed, with the same grain. They only rename and do light cleaning: no joins, no filters.

### `stg_customers` (one row per customer; from `raw_customers`)
| Column | Computed as |
|---|---|
| `customer_id` | `raw_customers.id`, renamed |
| `first_name` | `raw_customers.first_name`, unchanged |
| `last_name` | `raw_customers.last_name`, unchanged |
| `email` | `raw_customers.email`, trimmed and lower-cased |
| `country_code` | `raw_customers.country`, upper-cased |
| `signup_at` | `raw_customers.created_at`, renamed |

### `stg_orders` (one row per order; from `raw_orders`)
| Column | Computed as |
|---|---|
| `order_id` | `raw_orders.id`, renamed |
| `customer_id` | `raw_orders.user_id`, renamed |
| `order_date` | `raw_orders.order_date`, unchanged |
| `status` | `raw_orders.status`, unchanged |
| `tax_amount` | `raw_orders.tax_usd`, renamed (rename chain step 1) |

### `stg_order_items` (one row per order line; from `raw_order_items`)
| Column | Computed as |
|---|---|
| `order_item_id` | `raw_order_items.id`, renamed |
| `order_id` | unchanged |
| `product_id` | unchanged |
| `quantity` | unchanged |
| `unit_price` | unchanged (deep chain hop 1) |

### `stg_products` (one row per product; from `raw_products`)
| Column | Computed as |
|---|---|
| `product_id` | `raw_products.id`, renamed |
| `product_name` | `raw_products.name`, renamed |
| `category` | unchanged |
| `list_price` | unchanged |

### `stg_payments` (one row per payment; from `raw_payments`)
| Column | Computed as |
|---|---|
| `payment_id` | `raw_payments.id`, renamed |
| `order_id` | unchanged |
| `payment_method` | `raw_payments.method`, renamed |
| `amount_usd` | `raw_payments.amt`, renamed |
| `paid_at` | `raw_payments.created_at`, renamed |

### `stg_refunds` (one row per refund; from `raw_refunds`)
| Column | Computed as |
|---|---|
| `refund_id` | `raw_refunds.id`, renamed |
| `order_id` | unchanged |
| `refund_amt` | unchanged (near-duplicate name 1 of 3) |
| `refund_reason` | `raw_refunds.reason`, renamed |
| `refunded_at` | `raw_refunds.created_at`, renamed |

## Intermediate (5 models, 40 columns)

### `int_order_items_enriched` (one row per order line)
`stg_order_items` inner-joined to `stg_products` on `product_id`.
| Column | Computed as |
|---|---|
| `order_item_id` | `stg_order_items.order_item_id` |
| `order_id` | `stg_order_items.order_id` |
| `product_id` | `stg_order_items.product_id` |
| `product_category` | `stg_products.category`, renamed |
| `quantity` | `stg_order_items.quantity` |
| `unit_price` | `stg_order_items.unit_price` |
| `line_amount` | `quantity * unit_price` (deep chain hop 2) |
| `is_discounted` | `CASE WHEN unit_price < list_price THEN true ELSE false END` (CASE trap) |

### `int_orders_enriched` (one row per order)
`stg_orders` left-joined to a CTE that aggregates `int_order_items_enriched` per `order_id`.
| Column | Computed as |
|---|---|
| `order_id` | `stg_orders.order_id` |
| `customer_id` | `stg_orders.customer_id` |
| `order_date` | `stg_orders.order_date` |
| `order_status_group` | `CASE status`: `completed`→`complete`; `placed`/`shipped`→`open`; `return_pending`/`returned`→`returned`; else `other` (CASE trap) |
| `order_tax` | `stg_orders.tax_amount`, renamed (rename chain step 2) |
| `item_count` | `coalesce(sum(quantity), 0)` over the order's lines |
| `items_subtotal` | `coalesce(sum(line_amount), 0)` over the order's lines (deep chain hop 3) |

### `int_payment_events` (one row per payment or refund)
`stg_payments` UNION ALL `stg_refunds`, with the payments branch first. This is the cash ledger:
payments are positive and refunds negative.
| Column | Computed as |
|---|---|
| `event_id` | `'pay_' \|\| payment_id` in the payments branch; `'ref_' \|\| refund_id` in the refunds branch |
| `order_id` | `stg_payments.order_id` / `stg_refunds.order_id` |
| `event_amount_usd` | `stg_payments.amount_usd` (renamed) / `-1 * stg_refunds.refund_amt` |
| `event_at` | `stg_payments.paid_at` / `stg_refunds.refunded_at` (both renamed) |

### `int_order_financials` (one row per order)
`int_orders_enriched` left-joined to a refunds-per-order CTE (from `stg_refunds`) and a
cash-per-order CTE (from `int_payment_events`).
| Column | Computed as |
|---|---|
| `order_id` | `int_orders_enriched.order_id` |
| `customer_id` | `int_orders_enriched.customer_id` |
| `order_date` | `int_orders_enriched.order_date` |
| `order_status_group` | `int_orders_enriched.order_status_group` |
| `item_count` | `int_orders_enriched.item_count` |
| `items_subtotal` | `int_orders_enriched.items_subtotal` (deep chain hop 4) |
| `sales_tax` | `int_orders_enriched.order_tax`, renamed (rename chain step 3) |
| `order_total` | `items_subtotal + order_tax` |
| `refund_amount` | `coalesce(sum(stg_refunds.refund_amt), 0)` per order (near-duplicate name 2 of 3) |
| `net_paid_usd` | `coalesce(sum(int_payment_events.event_amount_usd), 0)` per order (payments minus refunds) |

### `int_customer_order_history` (one row per order)
`SELECT *, lag(order_date) OVER (PARTITION BY customer_id ORDER BY order_date, order_id) AS previous_order_date FROM int_order_financials`.
| Column | Computed as |
|---|---|
| the 10 columns of `int_order_financials` | passed through by `SELECT *`, unchanged (SELECT * trap) |
| `previous_order_date` | the customer's previous order's `order_date` (window trap); NULL for a first order |

## Marts (4 models, 32 columns)

### `fct_orders` (one row per order; from `int_customer_order_history`)
| Column | Computed as |
|---|---|
| `order_id` | unchanged |
| `customer_id` | unchanged |
| `order_date` | unchanged |
| `previous_order_date` | unchanged |
| `order_status_group` | unchanged |
| `item_count` | unchanged |
| `items_subtotal` | unchanged (deep chain hop 6) |
| `sales_tax` | unchanged |
| `order_total` | unchanged |
| `refunded_amount` | `refund_amount`, renamed (near-duplicate name 3 of 3) |
| `net_paid_usd` | unchanged |
| `revenue_finance` | `items_subtotal - refund_amount`: excludes tax, deducts refunds (finance definition) |
| `revenue_marketing` | `items_subtotal + sales_tax`: includes tax, does not deduct refunds (marketing definition) |
| `days_since_previous_order` | `order_date - previous_order_date` in days |

### `dim_customers` (one row per customer)
`stg_customers` left-joined to a CTE that aggregates `fct_orders` per `customer_id`.
| Column | Computed as |
|---|---|
| `customer_id` | `stg_customers.customer_id` |
| `full_name` | `first_name \|\| ' ' \|\| last_name` |
| `email` | `stg_customers.email` |
| `country_code` | `stg_customers.country_code` |
| `signup_at` | `stg_customers.signup_at` |
| `first_order_date` | `min(fct_orders.order_date)` |
| `most_recent_order_date` | `max(fct_orders.order_date)` |
| `order_count` | `coalesce(count(fct_orders.order_id), 0)` |
| `lifetime_value` | `coalesce(sum(items_subtotal + sales_tax - refunded_amount), 0)`: fan-in from 3 columns (fan-in trap) |

### `fct_daily_revenue` (one row per `order_date`; `fct_orders` grouped by `order_date`)
| Column | Computed as |
|---|---|
| `order_date` | the group key, `fct_orders.order_date` |
| `order_count` | `count(order_id)` |
| `revenue_finance` | `sum(revenue_finance)` (deep chain hop 7) |
| `revenue_marketing` | `sum(revenue_marketing)` |
| `refunded_amount` | `sum(refunded_amount)` |

### `fct_payment_events` (one row per payment or refund)
`SELECT * FROM int_payment_events` (SELECT * trap). It exposes the cash ledger to BI.
| Column | Computed as |
|---|---|
| `event_id`, `order_id`, `event_amount_usd`, `event_at` | passed through unchanged |

## Traps covered in v0.1

Full edge lists are in `traps.yml`.

| Trap | Where |
|---|---|
| Rename chain across 3 models | `raw_orders.tax_usd` → `stg_orders.tax_amount` → `int_orders_enriched.order_tax` → `int_order_financials.sales_tax` |
| `SELECT *` pass-through | `int_customer_order_history` (`SELECT *, window`), `fct_payment_events` (pure `SELECT *`) |
| Deep chain (7 hops) | `raw_order_items.unit_price` → … → `fct_daily_revenue.revenue_finance` (also → `dim_customers.lifetime_value`) |
| Fan-in aggregate from 3 sources | `dim_customers.lifetime_value` ← `items_subtotal`, `sales_tax`, `refunded_amount` |
| Two revenue definitions (plus a third revenue-like one) | `revenue_finance` vs `revenue_marketing` in `fct_orders` and `fct_daily_revenue`; also `dim_customers.lifetime_value` (see below) |
| Near-duplicate names | `stg_refunds.refund_amt`, `int_order_financials.refund_amount`, `fct_orders.refunded_amount` |
| CASE transformation | `int_orders_enriched.order_status_group`, `int_order_items_enriched.is_discounted` |
| Window function | `int_customer_order_history.previous_order_date` |
| UNION ALL | `int_payment_events` (8 edges, 2 branches) |

**Revenue-like definitions.** The `two_revenue_definitions` trap actually covers three
definitions, and each has a different upstream set:

| Column | Formula | Tax | Refunds |
|---|---|---|---|
| `revenue_finance` (`fct_orders`, summed in `fct_daily_revenue`) | `items_subtotal - refund_amount` | excluded | deducted |
| `revenue_marketing` (`fct_orders`, summed in `fct_daily_revenue`) | `items_subtotal + sales_tax` | included | not deducted |
| `dim_customers.lifetime_value` (summed per customer) | `items_subtotal + sales_tax - refunded_amount` | included | deducted |

`lifetime_value` matches neither named revenue column. It is not
`sum(revenue_finance)` because it includes tax, and it is not `sum(revenue_marketing)` because it
deducts refunds. Questions such as "is lifetime value based on finance revenue?" must be answered
from its three source edges, not from the word "revenue". No extra edges are needed: its three
existing fan-in edges are also tagged `two_revenue_definitions`.

Deferred to v0.3: join-key-only dependency, stale doc and exposures (spec §10).

## Deferred indirect edges

These columns are used only as join, group-by or window keys, so they are **not** v0.1 edges. They
become `phase: v0.3` edges (kinds JOIN / GROUP_BY / WINDOW) when indirect extraction is built.

| Model | Kind | Key column(s) | Role |
|---|---|---|---|
| `int_order_items_enriched` | JOIN | `stg_order_items.product_id`, `stg_products.product_id` | items ⋈ products |
| `int_orders_enriched` | JOIN | `stg_orders.order_id`, `int_order_items_enriched.order_id` | orders ⟕ item aggregate |
| `int_orders_enriched` | GROUP_BY | `int_order_items_enriched.order_id` | item aggregate per order (CTE) |
| `int_order_financials` | JOIN | `int_orders_enriched.order_id`, `stg_refunds.order_id` | orders ⟕ refunds per order |
| `int_order_financials` | JOIN | `int_orders_enriched.order_id`, `int_payment_events.order_id` | orders ⟕ cash per order |
| `int_order_financials` | GROUP_BY | `stg_refunds.order_id`, `int_payment_events.order_id` | per-order aggregates (CTEs) |
| `int_customer_order_history` | WINDOW | `int_order_financials.customer_id` (partition), `int_order_financials.order_date`, `int_order_financials.order_id` (order) | `previous_order_date` |
| `dim_customers` | JOIN | `stg_customers.customer_id`, `fct_orders.customer_id` | customers ⟕ order aggregate |
| `dim_customers` | GROUP_BY | `fct_orders.customer_id` | order aggregate per customer (CTE) |
| `fct_daily_revenue` | GROUP_BY | `fct_orders.order_date` | daily grain (also a direct IDENTITY edge to `order_date`) |

`fct_orders.customer_id` feeds `dim_customers` only through JOIN/GROUP BY, which makes it a natural
candidate for the v0.3 `join_key_only` trap.

## Summary

| Metric | Value |
|---|---|
| Seeds / seed columns | 6 / 30 |
| Models (staging / intermediate / marts) | **15** (6 / 5 / 4) |
| Model columns (staging / intermediate / marts) | **102** (30 / 40 / 32) |
| Direct edges (phase v0.1) | **115** |
| IDENTITY | 58 |
| RENAME | 22 |
| TRANSFORMATION | 21 |
| AGGREGATION | 14 |
| Indirect edges (phase v0.3) | 0 in spec; 10 key groups deferred (above) |
| Max hop depth (seed → model column, longest path) | **7** |
| Model columns at 6+ hops / 7 hops | 13 / 3 |

The depth histogram of model columns (longest path from a seed) is 1:30, 2:23, 3:13, 4:11, 5:12,
6:10, 7:3. The v0.3 target of ≥40 columns at 6+ hops (spec §10) is met when the corpus grows to 40–60
models.
