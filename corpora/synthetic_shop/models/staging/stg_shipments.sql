select
    id as shipment_id,
    order_id,
    lower(trim(carrier)) as carrier,
    shipped_at,
    delivered_at,
    shipping_cost_usd,
    date_diff('day', shipped_at, delivered_at) as delivery_days
from {{ ref('raw_shipments') }}
