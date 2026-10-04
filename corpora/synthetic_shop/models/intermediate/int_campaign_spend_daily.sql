select
    spend_date,
    channel,
    sum(spend_usd) as spend_usd,
    sum(impressions) as impressions,
    sum(clicks) as clicks,
    sum(clicks) / nullif(sum(impressions), 0) as click_through_rate
from {{ ref('stg_marketing_spend') }}
group by spend_date, channel
