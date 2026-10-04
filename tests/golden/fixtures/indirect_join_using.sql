select r.id as refund_id, r.refund_amt, p.pay_amt
from db.main.refunds as r
join db.main.payments as p using (order_id)
