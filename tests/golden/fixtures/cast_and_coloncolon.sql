select cast(amt as double) as amt_d, id::varchar as id_s, order_date::date as d from db.main.orders
