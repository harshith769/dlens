select c.id, c.name
from db.main.customers as c
where exists (
    select 1 from db.main.orders as o where o.user_id = c.id and o.status = 'paid'
)
