-- DESIGN_v2 §7.2 "Every LEFT JOIN has unmatched keys" (and matched ones). Returns one row per
-- case with no rows.
with checks as (
    select 'orders with no items' as join_case, count(*) as n
    from {{ ref('stg_orders') }}
    where order_id not in (select order_id from {{ ref('stg_order_items') }})
    union all
    select 'orders with no refunds', count(*)
    from {{ ref('stg_orders') }}
    where order_id not in (select order_id from {{ ref('stg_refunds') }})
    union all
    select 'orders with no payments', count(*)
    from {{ ref('stg_orders') }}
    where order_id not in (select order_id from {{ ref('stg_payments') }})
    union all
    select 'customers with no orders', count(*)
    from {{ ref('dim_customers') }} where order_count = 0
    union all
    select 'orders with no prior session', count(*)
    from {{ ref('int_order_attribution') }} where attributed_session_id is null
    union all
    select 'orders with a prior session', count(*)
    from {{ ref('int_order_attribution') }} where attributed_session_id is not null
    union all
    select 'orders with no shipment', count(*)
    from {{ ref('int_customer_order_history') }}
    where order_id not in (select order_id from {{ ref('int_order_shipping') }})
    union all
    select 'orders with no promotion', count(*)
    from {{ ref('int_customer_order_history') }}
    where order_id not in (select order_id from {{ ref('int_order_promotions') }})
    union all
    select 'orders with a promotion', count(*)
    from {{ ref('int_order_promotions') }}
    union all
    select 'customers with no sessions', count(*)
    from {{ ref('dim_customers') }}
    where customer_id not in (select customer_id from {{ ref('int_customer_sessions') }})
    union all
    select 'spend days with no sessions', count(*)
    from {{ ref('int_campaign_spend_daily') }} as spend
    left join {{ ref('int_sessions_daily') }} as sessions
        on spend.spend_date = sessions.session_date and spend.channel = sessions.channel
    where sessions.session_date is null
    union all
    select 'spend days with no attributed orders', count(*)
    from {{ ref('fct_marketing_attribution') }} where attributed_orders = 0
    union all
    select 'spend days with attributed orders', count(*)
    from {{ ref('fct_marketing_attribution') }} where attributed_orders > 0
    union all
    select 'stocked products never sold in a completed order', count(*)
    from {{ ref('fct_inventory_status') }}
    where product_id not in (select product_id from {{ ref('fct_product_performance') }})
)

select
    'every LEFT JOIN has unmatched keys' as guarantee,
    join_case,
    n
from checks
where n = 0
