select
    items.order_item_id,
    items.order_id,
    items.product_id,
    products.category as product_category,
    items.quantity,
    items.unit_price,
    items.quantity * items.unit_price as line_amount,
    case when items.unit_price < products.list_price then true else false end as is_discounted
from {{ ref('stg_order_items') }} as items
inner join {{ ref('stg_products') }} as products
    on items.product_id = products.product_id
