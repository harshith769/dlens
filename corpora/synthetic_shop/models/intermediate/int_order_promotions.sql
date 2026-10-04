select
    order_promotions.order_id,
    count(distinct order_promotions.promotion_id) as promotion_count,
    sum(order_promotions.discount_usd) as discount_total,
    max(promotions.discount_pct) as max_discount_pct,
    string_agg(promotions.promo_code, ',' order by promotions.discount_pct desc) as promo_codes
from {{ ref('stg_order_promotions') }} as order_promotions
inner join {{ ref('stg_promotions') }} as promotions
    on order_promotions.promotion_id = promotions.promotion_id
where order_promotions.promotion_id in (
    select promotion_id
    from {{ ref('stg_promotions') }}
    where promo_channel <> 'internal'
)
group by order_promotions.order_id
