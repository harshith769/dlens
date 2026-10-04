select
  user_id,
  status,
  sum(sum(amt)) over (partition by user_id order by status) as running_amt
from db.main.orders
group by user_id, status
