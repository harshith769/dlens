select
    user_id,
    string_agg(status, ',' order by order_date desc) as statuses,
    max(amt) as top_amt
from db.main.orders
group by user_id
