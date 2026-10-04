select
    session_date,
    channel,
    count(session_id) as session_count,
    count(distinct customer_id) as visitor_count,
    sum(page_views) as page_views
from {{ ref('int_web_sessions_clean') }}
group by session_date, channel
