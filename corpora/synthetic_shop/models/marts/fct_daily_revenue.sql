select
    order_date,
    count(order_id) as order_count,
    sum(revenue_finance) as revenue_finance,
    sum(revenue_marketing) as revenue_marketing,
    sum(refunded_amount) as refunded_amount
from {{ ref('fct_orders') }}
group by order_date
