select
    'pay_' || payment_id as event_id,
    order_id,
    amount_usd as event_amount_usd,
    paid_at as event_at
from {{ ref('stg_payments') }}

union all

select
    'ref_' || refund_id as event_id,
    order_id,
    -1 * refund_amt as event_amount_usd,
    refunded_at as event_at
from {{ ref('stg_refunds') }}
