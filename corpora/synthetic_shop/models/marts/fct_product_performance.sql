select
    items.product_id,
    products.product_name,
    products.category as product_category,
    sum(items.quantity) as units_sold,
    sum(items.quantity) filter (where items.is_discounted) as discounted_units,
    sum(items.line_amount) as gross_sales,
    sum(items.line_margin) as gross_margin
from {{ ref('int_order_item_margins') }} as items
inner join {{ ref('int_orders_enriched') }} as orders
    on items.order_id = orders.order_id
inner join {{ ref('stg_products') }} as products
    on items.product_id = products.product_id
where orders.order_status_group = 'complete'
group by items.product_id, products.product_name, products.category
