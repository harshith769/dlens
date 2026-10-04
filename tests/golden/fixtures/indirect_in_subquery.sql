select o.id, o.amt
from db.main.orders as o
where o.user_id in (
    select c.id from db.main.customers as c where c.region = 'EU'
)
