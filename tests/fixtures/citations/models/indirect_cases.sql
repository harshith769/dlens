with orders as (
    select order_id, customer_id from {{ ref('stg_orders') }}
),
enriched as (
    select cast(region as varchar) as region_code, customer_id from {{ ref('stg_customers') }}
)
select
    o.order_id,
    e.region_code
from orders as o
join enriched as e on o.customer_id = e.customer_id
where orders.customer_id > 0
