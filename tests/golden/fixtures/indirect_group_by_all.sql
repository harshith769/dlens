select user_id, status, sum(amt) as total from db.main.orders group by all
