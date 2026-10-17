{{ config(materialized='ephemeral') }}

select order_id, amount_cents
from {{ ref('raw_payments') }}
where amount_cents > 0
