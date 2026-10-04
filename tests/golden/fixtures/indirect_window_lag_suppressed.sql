select id, lag(amt) over (partition by user_id order by amt) as prev_amt from db.main.orders
