select o.id as order_id, c.name as customer_name, o.amt, c.region
from db.main.orders as o join db.main.customers as c on o.user_id = c.id
