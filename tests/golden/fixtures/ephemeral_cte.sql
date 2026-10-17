with __dbt__cte__paid as (
    select id, user_id, amt * 2 as amt2 from db.main.orders where status = 'paid'
)
select p.id as order_id, p.amt2 as total, c.name
from __dbt__cte__paid as p
join db.main.customers as c on p.user_id = c.id
