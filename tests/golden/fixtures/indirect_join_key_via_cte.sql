with paid as (
    select order_id, sum(pay_amt) as paid_amt from db.main.payments group by order_id
)
select o.id, o.amt, paid.paid_amt
from db.main.orders as o
left join paid on o.id = paid.order_id
