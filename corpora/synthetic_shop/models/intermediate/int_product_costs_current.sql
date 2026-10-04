select
    costs.product_id,
    costs.supplier_id,
    costs.unit_cost,
    costs.valid_from as cost_valid_from,
    suppliers.supplier_name,
    suppliers.supplier_country,
    suppliers.lead_time_days
from {{ ref('stg_product_costs') }} as costs
inner join {{ ref('stg_suppliers') }} as suppliers
    on costs.supplier_id = suppliers.supplier_id
qualify row_number() over (
    partition by costs.product_id
    order by costs.valid_from desc
) = 1
