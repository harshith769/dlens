select
    items.order_item_id,
    items.order_id,
    items.product_id,
    items.quantity,
    items.line_amount,
    items.is_discounted,
    costs.unit_cost,
    costs.supplier_id,
    items.quantity * costs.unit_cost as line_cost,
    items.line_amount - items.quantity * costs.unit_cost as line_margin
from {{ ref('int_order_items_enriched') }} as items
inner join {{ ref('int_product_costs_current') }} as costs
    on items.product_id = costs.product_id
