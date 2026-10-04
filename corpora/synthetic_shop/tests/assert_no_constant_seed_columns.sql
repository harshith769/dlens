-- DESIGN_v2 §7.2 "No constant columns": every seed column has >= 2 distinct non-null values
-- (so is_bot has both values). Returns one row per violating column.
{% set seeds = {
    'raw_customers': ['id', 'first_name', 'last_name', 'email', 'country', 'created_at'],
    'raw_orders': ['id', 'user_id', 'order_date', 'status', 'tax_usd'],
    'raw_order_items': ['id', 'order_id', 'product_id', 'quantity', 'unit_price'],
    'raw_products': ['id', 'name', 'category', 'list_price'],
    'raw_payments': ['id', 'order_id', 'method', 'amt', 'created_at'],
    'raw_refunds': ['id', 'order_id', 'refund_amt', 'reason', 'created_at'],
    'raw_shipments': ['id', 'order_id', 'carrier', 'shipped_at', 'delivered_at', 'shipping_cost_usd'],
    'raw_web_sessions': ['id', 'user_id', 'started_at', 'channel', 'utm_campaign', 'page_views', 'is_bot'],
    'raw_marketing_spend': ['spend_day', 'channel', 'campaign', 'spend_usd', 'impressions', 'clicks'],
    'raw_promotions': ['id', 'code', 'discount_pct', 'starts_at', 'ends_at', 'channel'],
    'raw_order_promotions': ['id', 'order_id', 'promotion_id', 'discount_usd'],
    'raw_suppliers': ['id', 'name', 'country', 'lead_time_days'],
    'raw_product_costs': ['id', 'product_id', 'supplier_id', 'unit_cost', 'valid_from'],
    'raw_inventory_snapshots': ['id', 'product_id', 'snapshot_date', 'qty_on_hand', 'warehouse'],
} %}

with distinct_counts as (
{%- for seed, columns in seeds.items() %}
{%- set outer_loop = loop %}
{%- for column in columns %}
    select
        '{{ seed }}.{{ column }}' as seed_column,
        count(distinct {{ column }}) as distinct_values
    from {{ ref(seed) }}
    {%- if not (outer_loop.last and loop.last) %}
    union all
    {%- endif %}
{%- endfor %}
{%- endfor %}
)

select
    'no constant columns' as guarantee,
    seed_column,
    distinct_values
from distinct_counts
where distinct_values < 2
