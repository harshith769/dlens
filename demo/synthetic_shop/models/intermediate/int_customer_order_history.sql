select
    *,
    lag(order_date) over (
        partition by customer_id
        order by order_date, order_id
    ) as previous_order_date
from {{ ref('int_order_financials') }}
