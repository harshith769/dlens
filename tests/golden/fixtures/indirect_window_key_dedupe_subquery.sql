select id, user_id, amt
from (
    select id, user_id, amt,
        row_number() over (partition by user_id order by order_date desc) as rn
    from db.main.orders
) as t
where rn = 1
