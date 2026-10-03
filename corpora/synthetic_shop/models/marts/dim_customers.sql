with order_agg as (
    select
        customer_id,
        min(order_date) as first_order_date,
        max(order_date) as most_recent_order_date,
        count(order_id) as order_count,
        sum(items_subtotal + sales_tax - refunded_amount) as lifetime_value
    from {{ ref('fct_orders') }}
    group by customer_id
)

select
    customers.customer_id,
    customers.first_name || ' ' || customers.last_name as full_name,
    customers.email,
    customers.country_code,
    customers.signup_at,
    order_agg.first_order_date,
    order_agg.most_recent_order_date,
    coalesce(order_agg.order_count, 0) as order_count,
    coalesce(order_agg.lifetime_value, 0) as lifetime_value
from {{ ref('stg_customers') }} as customers
left join order_agg
    on customers.customer_id = order_agg.customer_id
