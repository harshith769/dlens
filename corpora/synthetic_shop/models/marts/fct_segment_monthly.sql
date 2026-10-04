select
    date_trunc('month', orders.order_date) as order_month,
    segments.customer_segment,
    count(orders.order_id) as segment_order_count,
    count(distinct orders.customer_id) as active_customers,
    sum(orders.revenue_finance) as segment_revenue_finance
from {{ ref('fct_orders') }} as orders
inner join {{ ref('dim_customer_segments') }} as segments
    on orders.customer_id = segments.customer_id
group by segments.customer_segment, date_trunc('month', orders.order_date)
