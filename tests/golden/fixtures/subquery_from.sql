select s.user_id, s.total + 1 as total_plus
from (select user_id, sum(amt) as total from db.main.orders group by user_id) as s
