with orders as (
    select * from {{ ref('raw_orders') }}
)

select
    orders.id as order_id,
    orders.customer_id,
    orders.order_date,
    p.amount_usd,
    row_number() over (partition by orders.customer_id order by orders.order_date) as order_seq
from orders
left join {{ ref('order_payments') }} as p on orders.id = p.order_id
where orders.status <> 'returned'
