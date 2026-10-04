select
    * exclude (is_profitable),
    contribution_margin / nullif(net_revenue, 0) as margin_pct
from {{ ref('int_order_profit') }}
