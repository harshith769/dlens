select
    'promo_' || order_promotion_id as adjustment_id,
    order_id,
    -1 * discount_usd as adjustment_amount_usd
from {{ ref('stg_order_promotions') }}

union all

select
    'ref_' || refund_id as adjustment_id,
    order_id,
    -1 * refund_amt as adjustment_amount_usd
from {{ ref('stg_refunds') }}

union all

select
    'ship_' || shipment_id as adjustment_id,
    order_id,
    -1 * shipping_cost_usd as adjustment_amount_usd
from {{ ref('stg_shipments') }}
