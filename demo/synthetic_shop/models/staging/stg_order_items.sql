select
    id as order_item_id,
    order_id,
    product_id,
    quantity,
    unit_price
from {{ ref('raw_order_items') }}
