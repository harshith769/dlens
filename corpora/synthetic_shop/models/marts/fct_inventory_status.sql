with latest_snapshots as (
    select
        product_id,
        warehouse_code,
        snapshot_date,
        qty_on_hand,
        inventory_value
    from {{ ref('int_inventory_daily') }}
    qualify row_number() over (
        partition by product_id, warehouse_code
        order by snapshot_date desc
    ) = 1
)

select
    latest_snapshots.product_id,
    latest_snapshots.warehouse_code,
    latest_snapshots.snapshot_date as as_of_date,
    latest_snapshots.qty_on_hand,
    latest_snapshots.inventory_value,
    latest_snapshots.qty_on_hand / nullif(performance.units_sold / 365.0, 0) as days_of_cover
from latest_snapshots
left join {{ ref('fct_product_performance') }} as performance
    on latest_snapshots.product_id = performance.product_id
order by latest_snapshots.warehouse_code, latest_snapshots.product_id
