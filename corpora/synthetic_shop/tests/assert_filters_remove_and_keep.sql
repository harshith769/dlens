-- DESIGN_v2 §7.2 "Every WHERE removes >= 1 row and keeps >= 1" (QUALIFY included).
-- Returns one row per filter that removes nothing or keeps nothing.
with sessions_per_order as (
    select orders.order_id, count(sessions.session_id) as eligible_sessions
    from {{ ref('int_customer_order_history') }} as orders
    inner join {{ ref('int_web_sessions_clean') }} as sessions
        on orders.customer_id = sessions.customer_id
        and sessions.session_date <= orders.order_date
    group by orders.order_id
),

checks as (
    select 'int_web_sessions_clean removes bots' as filter_case, count(*) as n
    from {{ ref('stg_web_sessions') }} where is_bot
    union all
    select 'int_web_sessions_clean removes empty human sessions', count(*)
    from {{ ref('stg_web_sessions') }} where not is_bot and page_views = 0
    union all
    select 'int_web_sessions_clean keeps sessions', count(*)
    from {{ ref('int_web_sessions_clean') }}
    union all
    select 'int_customer_sessions removes anonymous sessions', count(*)
    from {{ ref('int_web_sessions_clean') }} where customer_id is null
    union all
    select 'int_customer_sessions keeps known customers', count(*)
    from {{ ref('int_web_sessions_clean') }} where customer_id is not null
    union all
    select 'int_order_promotions removes internal promotions used by orders', count(*)
    from {{ ref('stg_order_promotions') }} as order_promotions
    inner join {{ ref('stg_promotions') }} as promotions
        on order_promotions.promotion_id = promotions.promotion_id
    where promotions.promo_channel = 'internal'
    union all
    select 'int_order_promotions keeps other promotions', count(*)
    from {{ ref('stg_order_promotions') }} as order_promotions
    inner join {{ ref('stg_promotions') }} as promotions
        on order_promotions.promotion_id = promotions.promotion_id
    where promotions.promo_channel <> 'internal'
    union all
    select 'int_inventory_daily removes WH_TEST', count(*)
    from {{ ref('stg_inventory_snapshots') }} where warehouse_code = 'WH_TEST'
    union all
    select 'int_inventory_daily keeps other warehouses', count(*)
    from {{ ref('stg_inventory_snapshots') }} where warehouse_code <> 'WH_TEST'
    union all
    select 'fct_product_performance removes non-complete orders with items', count(*)
    from {{ ref('int_order_item_margins') }} as items
    inner join {{ ref('int_orders_enriched') }} as orders on items.order_id = orders.order_id
    where orders.order_status_group <> 'complete'
    union all
    select 'fct_product_performance keeps complete orders', count(*)
    from {{ ref('int_order_item_margins') }} as items
    inner join {{ ref('int_orders_enriched') }} as orders on items.order_id = orders.order_id
    where orders.order_status_group = 'complete'
    union all
    select 'fct_shipping_performance removes unshipped shipments', count(*)
    from {{ ref('int_shipments_enriched') }} where shipped_at is null
    union all
    select 'fct_shipping_performance keeps shipped shipments', count(*)
    from {{ ref('int_shipments_enriched') }} where shipped_at is not null
    union all
    select 'QUALIFY int_product_costs_current: products with >= 2 cost rows', count(*)
    from (
        select product_id from {{ ref('stg_product_costs') }}
        group by product_id having count(*) >= 2
    ) as history
    union all
    select 'QUALIFY int_order_attribution: orders with >= 2 earlier sessions', count(*)
    from sessions_per_order where eligible_sessions >= 2
    union all
    select 'QUALIFY fct_inventory_status: product x warehouse with >= 2 snapshots', count(*)
    from (
        select product_id, warehouse_code from {{ ref('int_inventory_daily') }}
        group by product_id, warehouse_code having count(*) >= 2
    ) as stocked
)

select
    'every WHERE removes >= 1 row and keeps >= 1' as guarantee,
    filter_case,
    n
from checks
where n = 0
