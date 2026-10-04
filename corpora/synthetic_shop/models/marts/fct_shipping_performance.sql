select
    carrier,
    date_trunc('month', shipped_at) as ship_month,
    count(shipment_id) as shipment_count,
    sum(case when is_late_delivery then 1 else 0 end) as late_shipment_count,
    avg(delivery_days) as avg_delivery_days,
    sum(shipping_cost_usd) as shipping_costs_usd
from {{ ref('int_shipments_enriched') }}
where shipped_at is not null
group by carrier, date_trunc('month', shipped_at)
