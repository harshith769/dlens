select
    customer_id,
    count(session_id) as session_count,
    count(session_id) filter (where channel <> 'direct') as paid_session_count,
    min(session_started_at) as first_session_at,
    max(session_started_at) as last_session_at,
    sum(page_views) as total_page_views
from {{ ref('int_web_sessions_clean') }}
where customer_id is not null
group by customer_id
