select
    c.customer_id,
    c.full_name,
    count(co.order_id) as order_count,
    sum(co.amount_usd) as lifetime_usd
from "eph_shop"."main"."stg_customers" as c
left join "eph_shop"."main"."customer_orders" as co on c.customer_id = co.customer_id
group by c.customer_id, c.full_name