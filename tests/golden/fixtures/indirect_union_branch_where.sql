select id, amt as amount from db.main.orders where status = 'paid'
union all
select id, refund_amt from db.main.refunds
