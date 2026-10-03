select id, user_id as party from db.main.orders
union
select id, id from db.main.customers
