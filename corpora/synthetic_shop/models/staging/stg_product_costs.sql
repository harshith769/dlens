select
    id as product_cost_id,
    product_id,
    supplier_id,
    unit_cost,
    valid_from
from {{ ref('raw_product_costs') }}
