-- The two approved v1 CSV appends (DESIGN_v2 §1 item 4). Cancelled orders belong to customers
-- with v1 orders, carry tax 0, a date in the v1 range and nothing else; product 16 has costs and
-- stock in >= 2 real warehouses but no order items. Returns one row per broken rule.
with cancelled as (
    select * from {{ ref('raw_orders') }} where status = 'cancelled'
),

v1_orders as (
    select * from {{ ref('raw_orders') }} where status <> 'cancelled'
),

checks as (
    select 'cancelled orders exist' as rule, case when count(*) > 0 then 0 else 1 end as bad
    from cancelled
    union all
    select 'cancelled orders: customer has v1 orders', count(*)
    from cancelled where user_id not in (select user_id from v1_orders)
    union all
    select 'cancelled orders: tax 0 and date in the v1 range', count(*)
    from cancelled
    where tax_usd <> 0
        or order_date < (select min(order_date) from v1_orders)
        or order_date > (select max(order_date) from v1_orders)
    {% for seed in ['raw_order_items', 'raw_payments', 'raw_refunds', 'raw_shipments', 'raw_order_promotions'] %}
    union all
    select 'cancelled orders: no rows in {{ seed }}', count(*)
    from {{ ref(seed) }} where order_id in (select id from cancelled)
    {% endfor %}
    union all
    select 'product 16: no order items', count(*)
    from {{ ref('raw_order_items') }} where product_id = 16
    union all
    select 'product 16: has a cost row', case when count(*) > 0 then 0 else 1 end
    from {{ ref('raw_product_costs') }} where product_id = 16
    union all
    select 'product 16: stocked in >= 2 real warehouses',
        case when count(distinct warehouse_code) >= 2 then 0 else 1 end
    from {{ ref('stg_inventory_snapshots') }}
    where product_id = 16 and warehouse_code <> 'WH_TEST'
)

select
    'approved v1 appends' as guarantee,
    rule,
    bad
from checks
where bad <> 0
