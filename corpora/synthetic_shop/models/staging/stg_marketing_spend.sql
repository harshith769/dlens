select
    spend_day as spend_date,
    lower(channel) as channel,
    campaign as campaign_name,
    spend_usd,
    impressions,
    clicks
from {{ ref('raw_marketing_spend') }}
