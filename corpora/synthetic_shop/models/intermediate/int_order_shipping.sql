select
    order_id,
    count(shipment_id) as shipment_count,
    sum(shipping_cost_usd) as shipping_cost_total,
    min(shipped_at) as first_shipped_at,
    max(delivered_at) as last_delivered_at,
    count(shipment_id) filter (where is_late_delivery) as late_shipment_count
from {{ ref('int_shipments_enriched') }}
group by order_id
