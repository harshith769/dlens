select
    id as session_id,
    user_id as customer_id,
    started_at as session_started_at,
    lower(channel) as channel,
    utm_campaign,
    page_views,
    is_bot
from {{ ref('raw_web_sessions') }}
