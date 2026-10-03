select
    id as payment_id,
    order_id,
    method as payment_method,
    amt as amount_usd,
    created_at as paid_at
from {{ ref('raw_payments') }}
