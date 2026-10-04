select
    id as promotion_id,
    upper(code) as promo_code,
    discount_pct,
    starts_at,
    ends_at,
    channel as promo_channel
from {{ ref('raw_promotions') }}
