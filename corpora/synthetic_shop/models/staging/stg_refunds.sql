select
    id as refund_id,
    order_id,
    refund_amt,
    reason as refund_reason,
    created_at as refunded_at
from {{ ref('raw_refunds') }}
