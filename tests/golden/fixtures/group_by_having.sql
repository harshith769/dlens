select user_id, sum(amt) as total, count(*) as n from db.main.orders group by user_id having max(tax) > 0
