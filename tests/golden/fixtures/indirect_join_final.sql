select o.id, c.name
from db.main.orders as o
left join db.main.customers as c on o.user_id = c.id and o.amt > 0
