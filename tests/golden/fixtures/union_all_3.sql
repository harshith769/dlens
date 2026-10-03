select id, pay_amt as amount from db.main.payments
union all
select id, -1 * refund_amt from db.main.refunds
union all
select id, amt from db.main.orders
