select
    id as product_id,
    name as product_name,
    category,
    list_price
from {{ ref('raw_products') }}
