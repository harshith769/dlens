with  __dbt__cte__paid_payments as (


select order_id, amount_cents
from "eph_shop"."main"."raw_payments"
where amount_cents > 0
),  __dbt__cte__order_payments as (


select
    order_id,
    sum(amount_cents) / 100.0 as amount_usd
from __dbt__cte__paid_payments
group by order_id
), orders as (
    select * from "eph_shop"."main"."raw_orders"
)

select
    orders.id as order_id,
    orders.customer_id,
    orders.order_date,
    p.amount_usd,
    row_number() over (partition by orders.customer_id order by orders.order_date) as order_seq
from orders
left join __dbt__cte__order_payments as p on orders.id = p.order_id
where orders.status <> 'returned'