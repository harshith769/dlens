select
    orders.order_id,
    orders.customer_id,
    orders.order_date,
    sessions.session_id as attributed_session_id,
    coalesce(sessions.channel, 'direct') as attributed_channel,
    sessions.utm_campaign as attributed_campaign,
    orders.items_subtotal + orders.sales_tax as attributed_revenue,
    date_diff('day', sessions.session_date, orders.order_date) as days_to_convert
from {{ ref('int_customer_order_history') }} as orders
left join {{ ref('int_web_sessions_clean') }} as sessions
    on orders.customer_id = sessions.customer_id
    and sessions.session_date <= orders.order_date
qualify row_number() over (
    partition by orders.order_id
    order by sessions.session_started_at desc, sessions.session_id desc
) = 1
