with a as (select id, amt as amount, user_id from db.main.orders),
b as (select id, amount * 2 as doubled, user_id from a),
c as (select id as order_id, doubled, user_id from b)
select order_id, doubled as total, user_id from c
