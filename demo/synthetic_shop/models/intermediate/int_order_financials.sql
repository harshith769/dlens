with refunds_per_order as (
    select
        order_id,
        sum(refund_amt) as refund_amount
    from {{ ref('stg_refunds') }}
    group by order_id
),

cash_per_order as (
    select
        order_id,
        sum(event_amount_usd) as net_paid_usd
    from {{ ref('int_payment_events') }}
    group by order_id
)

select
    orders.order_id,
    orders.customer_id,
    orders.order_date,
    orders.order_status_group,
    orders.item_count,
    orders.items_subtotal,
    orders.order_tax as sales_tax,
    orders.items_subtotal + orders.order_tax as order_total,
    coalesce(refunds_per_order.refund_amount, 0) as refund_amount,
    coalesce(cash_per_order.net_paid_usd, 0) as net_paid_usd
from {{ ref('int_orders_enriched') }} as orders
left join refunds_per_order
    on orders.order_id = refunds_per_order.order_id
left join cash_per_order
    on orders.order_id = cash_per_order.order_id
