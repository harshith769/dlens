select
    id as snapshot_id,
    product_id,
    snapshot_date,
    qty_on_hand,
    upper(warehouse) as warehouse_code
from {{ ref('raw_inventory_snapshots') }}
