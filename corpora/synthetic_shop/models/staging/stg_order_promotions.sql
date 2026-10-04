select
    id as order_promotion_id,
    order_id,
    promotion_id,
    discount_usd
from {{ ref('raw_order_promotions') }}
