select
    product_id,
    product_name,
    units_sold,
    gross_margin
from {{ ref('fct_product_performance') }}
order by gross_margin desc, product_id
limit 10
