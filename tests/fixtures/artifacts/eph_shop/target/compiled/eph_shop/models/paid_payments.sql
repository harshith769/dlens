

select order_id, amount_cents
from "eph_shop"."main"."raw_payments"
where amount_cents > 0