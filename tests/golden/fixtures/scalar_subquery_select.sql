select o.id,
  (select max(c.name) from db.main.customers as c where c.id = o.user_id) as cust_name
from db.main.orders as o
