select
    order_id,
    customer_id,
    order_date,
    previous_order_date,
    order_status_group,
    item_count,
    items_subtotal,
    sales_tax,
    order_total,
    refund_amount as refunded_amount,
    net_paid_usd,
    items_subtotal - refund_amount as revenue_finance,
    items_subtotal + sales_tax as revenue_marketing,
    order_date - previous_order_date as days_since_previous_order
from {{ ref('int_customer_order_history') }}
