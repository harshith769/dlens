select
    id as order_id,
    user_id as customer_id,
    order_date,
    status,
    tax_usd as tax_amount
from {{ ref('raw_orders') }}
