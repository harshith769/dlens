with per_user as (
    select user_id, count(id) as n_orders from db.main.orders group by user_id
)
select c.id, c.name, per_user.n_orders
from db.main.customers as c
join per_user on c.id = per_user.user_id
