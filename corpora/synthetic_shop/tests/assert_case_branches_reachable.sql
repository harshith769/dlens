-- DESIGN_v2 §7.2 "Every CASE branch reachable", plus rows on both sides of the CASE thresholds.
-- Returns one row per branch that no row reaches.
with branches as (
    {% for value in ['complete', 'open', 'returned', 'other'] %}
    select 'order_status_group = {{ value }}' as branch, count(*) as n
    from {{ ref('int_orders_enriched') }} where order_status_group = '{{ value }}'
    union all
    {% endfor %}
    {% for value in ['true', 'false'] %}
    select 'is_discounted = {{ value }}', count(*)
    from {{ ref('int_order_items_enriched') }} where is_discounted = {{ value }}
    union all
    select 'is_late_delivery = {{ value }}', count(*)
    from {{ ref('int_shipments_enriched') }} where is_late_delivery = {{ value }}
    union all
    select 'is_profitable = {{ value }}', count(*)
    from {{ ref('int_order_profit') }} where is_profitable = {{ value }}
    union all
    select 'is_high_value = {{ value }}', count(*)
    from {{ ref('dim_customer_segments') }} where is_high_value = {{ value }}
    union all
    {% endfor %}
    {% for level in [1, 2, 3] %}
    {% for score in ['rfm_recency_score', 'rfm_frequency_score', 'rfm_monetary_score'] %}
    select '{{ score }} = {{ level }}', count(*)
    from {{ ref('dim_customer_rfm') }} where {{ score }} = {{ level }}
    union all
    {% endfor %}
    {% endfor %}
    {% for value in ['champion', 'loyal', 'at_risk', 'hibernating'] %}
    select 'customer_segment = {{ value }}', count(*)
    from {{ ref('dim_customer_segments') }} where customer_segment = '{{ value }}'
    union all
    {% endfor %}
    -- delivery_days threshold: a 1-day step crosses it both ways. RFM cut-offs: both sides are
    -- covered by the score levels above; the perturbation step is set in A4.
    select 'delivery_days = 5 (not late)', count(*)
    from {{ ref('int_shipments_enriched') }} where delivery_days = 5
    union all
    select 'delivery_days = 6 (late)', count(*)
    from {{ ref('int_shipments_enriched') }} where delivery_days = 6
)

select
    'every CASE branch reachable' as guarantee,
    branch,
    n
from branches
where n = 0
