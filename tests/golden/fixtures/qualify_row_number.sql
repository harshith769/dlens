select id, user_id, amt from db.main.orders
qualify row_number() over (partition by user_id order by order_date desc) = 1
