with item_margins as (
    select
        order_id,
        sum(line_cost) as cogs_total,
        sum(line_margin) as gross_margin
    from {{ ref('int_order_item_margins') }}
    group by order_id
)

select
    orders.order_id,
    orders.customer_id,
    orders.order_date,
    orders.items_subtotal - orders.refund_amount - coalesce(promotions.discount_total, 0) as net_revenue,
    coalesce(item_margins.cogs_total, 0) as cogs_total,
    coalesce(item_margins.gross_margin, 0) as gross_margin,
    coalesce(shipping.shipping_cost_total, 0) as shipping_cost_total,
    coalesce(promotions.discount_total, 0) as discount_total,
    coalesce(item_margins.gross_margin, 0)
        - coalesce(shipping.shipping_cost_total, 0)
        - coalesce(promotions.discount_total, 0) as contribution_margin,
    case
        when coalesce(item_margins.gross_margin, 0)
            - coalesce(shipping.shipping_cost_total, 0)
            - coalesce(promotions.discount_total, 0) > 0 then true
        else false
    end as is_profitable
from {{ ref('int_customer_order_history') }} as orders
left join item_margins
    on orders.order_id = item_margins.order_id
left join {{ ref('int_order_shipping') }} as shipping
    on orders.order_id = shipping.order_id
left join {{ ref('int_order_promotions') }} as promotions
    on orders.order_id = promotions.order_id
