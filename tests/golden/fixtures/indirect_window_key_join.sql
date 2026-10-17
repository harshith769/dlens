with ranked as (
    select id, user_id, amt,
        row_number() over (partition by user_id order by order_date) as order_seq
    from db.main.orders
)
select c.id as customer_id, c.name, r.amt as first_order_amt
from db.main.customers as c
left join ranked as r on c.id = r.user_id and r.order_seq = 1
