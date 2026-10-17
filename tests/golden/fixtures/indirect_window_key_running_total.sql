select id, user_id, running_total
from (
    select id, user_id,
        sum(amt) over (partition by user_id order by order_date) as running_total
    from db.main.orders
) as t
where running_total > 100
