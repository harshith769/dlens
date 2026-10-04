select
    date_trunc('month', report_date) as report_month,
    channel,
    sum(spend_usd) as spend_usd,
    sum(attributed_revenue) as attributed_revenue,
    sum(attributed_revenue) / nullif(sum(spend_usd), 0) as roas
from {{ ref('fct_marketing_attribution') }}
group by date_trunc('month', report_date), channel
