-- DESIGN_v2 §7.2 "INNER JOINs drop nothing". Returns one row per join that loses rows.
with checks as (
    select 'every product has a cost row' as join_case, count(*) as lost
    from {{ ref('stg_products') }}
    where product_id not in (select product_id from {{ ref('stg_product_costs') }})
    union all
    select 'every cost row has a known supplier', count(*)
    from {{ ref('stg_product_costs') }}
    where supplier_id not in (select supplier_id from {{ ref('stg_suppliers') }})
    union all
    select 'every shipment has a known order', count(*)
    from {{ ref('stg_shipments') }}
    where order_id not in (select order_id from {{ ref('stg_orders') }})
    union all
    select 'int_product_costs_current has one row per costed product',
        (select count(distinct product_id) from {{ ref('stg_product_costs') }})
        - (select count(*) from {{ ref('int_product_costs_current') }})
    union all
    select 'int_order_item_margins keeps every order line',
        (select count(*) from {{ ref('int_order_items_enriched') }})
        - (select count(*) from {{ ref('int_order_item_margins') }})
    union all
    select 'int_shipments_enriched keeps every shipment',
        (select count(*) from {{ ref('stg_shipments') }})
        - (select count(*) from {{ ref('int_shipments_enriched') }})
)

select
    'INNER JOINs drop nothing' as guarantee,
    join_case,
    lost
from checks
where lost <> 0
