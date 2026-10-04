select
    session_id,
    customer_id,
    session_started_at,
    channel,
    utm_campaign,
    page_views,
    cast(session_started_at as date) as session_date,
    row_number() over (
        partition by customer_id
        order by session_started_at, session_id
    ) as session_number
from {{ ref('stg_web_sessions') }}
where not is_bot
    and page_views > 0
