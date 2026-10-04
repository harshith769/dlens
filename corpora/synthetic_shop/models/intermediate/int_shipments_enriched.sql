select
    shipments.shipment_id,
    shipments.order_id,
    shipments.carrier,
    shipments.shipped_at,
    shipments.delivered_at,
    shipments.delivery_days,
    shipments.shipping_cost_usd,
    date_diff('day', orders.order_date, shipments.shipped_at) as days_to_ship,
    case when shipments.delivery_days > 5 then true else false end as is_late_delivery
from {{ ref('stg_shipments') }} as shipments
inner join {{ ref('stg_orders') }} as orders
    on shipments.order_id = orders.order_id
