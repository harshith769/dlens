select
    customers.customer_id,
    customers.full_name,
    customers.lifetime_value as lifetime_value_usd,
    segments.customer_segment
from {{ ref('dim_customers') }} as customers
inner join {{ ref('dim_customer_segments') }} as segments
    on customers.customer_id = segments.customer_id
order by customers.lifetime_value desc, customers.customer_id
limit 20
