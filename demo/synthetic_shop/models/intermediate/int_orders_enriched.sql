with item_agg as (
    select
        order_id,
        sum(quantity) as item_count,
        sum(line_amount) as items_subtotal
    from {{ ref('int_order_items_enriched') }}
    group by order_id
)

select
    orders.order_id,
    orders.customer_id,
    orders.order_date,
    case orders.status
        when 'completed' then 'complete'
        when 'placed' then 'open'
        when 'shipped' then 'open'
        when 'return_pending' then 'returned'
        when 'returned' then 'returned'
        else 'other'
    end as order_status_group,
    orders.tax_amount as order_tax,
    coalesce(item_agg.item_count, 0) as item_count,
    coalesce(item_agg.items_subtotal, 0) as items_subtotal
from {{ ref('stg_orders') }} as orders
left join item_agg
    on orders.order_id = item_agg.order_id
