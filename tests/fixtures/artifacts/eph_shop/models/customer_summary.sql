select
    c.customer_id,
    c.full_name,
    count(co.order_id) as order_count,
    sum(co.amount_usd) as lifetime_usd
from {{ ref('stg_customers') }} as c
left join {{ ref('customer_orders') }} as co on c.customer_id = co.customer_id
group by c.customer_id, c.full_name
