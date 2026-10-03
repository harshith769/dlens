select id, sum(amt) over (partition by user_id order by order_date) as running_amt from db.main.orders
