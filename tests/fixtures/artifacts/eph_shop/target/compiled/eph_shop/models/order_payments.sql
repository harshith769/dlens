

with __dbt__cte__paid_payments as (


select order_id, amount_cents
from "eph_shop"."main"."raw_payments"
where amount_cents > 0
) select
    order_id,
    sum(amount_cents) / 100.0 as amount_usd
from __dbt__cte__paid_payments
group by order_id