select
    snapshots.product_id,
    snapshots.snapshot_date,
    snapshots.warehouse_code,
    snapshots.qty_on_hand,
    snapshots.qty_on_hand * products.list_price as inventory_value,
    lag(snapshots.qty_on_hand) over (
        partition by snapshots.product_id, snapshots.warehouse_code
        order by snapshots.snapshot_date
    ) as prior_qty_on_hand,
    snapshots.qty_on_hand - lag(snapshots.qty_on_hand) over (
        partition by snapshots.product_id, snapshots.warehouse_code
        order by snapshots.snapshot_date
    ) as qty_change
from {{ ref('stg_inventory_snapshots') }} as snapshots
inner join {{ ref('stg_products') }} as products
    on snapshots.product_id = products.product_id
where snapshots.warehouse_code <> 'WH_TEST'
