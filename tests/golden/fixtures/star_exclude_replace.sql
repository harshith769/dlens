select * exclude (price) replace (qty * 2 as qty) from db.main.order_items
