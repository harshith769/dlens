{{ config(materialized='ephemeral') }}

select
    order_id,
    sum(amount_cents) / 100.0 as amount_usd
from {{ ref('paid_payments') }}
group by order_id
