with attributed_daily as (
    select
        order_date,
        attributed_channel,
        count(order_id) as attributed_orders,
        sum(attributed_revenue) as attributed_revenue
    from {{ ref('int_order_attribution') }}
    group by order_date, attributed_channel
)

select
    spend.spend_date as report_date,
    spend.channel,
    spend.spend_usd,
    coalesce(sessions.session_count, 0) as session_count,
    coalesce(attributed_daily.attributed_orders, 0) as attributed_orders,
    coalesce(attributed_daily.attributed_revenue, 0) as attributed_revenue,
    spend.spend_usd / nullif(attributed_daily.attributed_orders, 0) as cost_per_order,
    coalesce(attributed_daily.attributed_revenue, 0) / nullif(spend.spend_usd, 0) as roas
from {{ ref('int_campaign_spend_daily') }} as spend
left join {{ ref('int_sessions_daily') }} as sessions
    on spend.spend_date = sessions.session_date
    and spend.channel = sessions.channel
left join attributed_daily
    on spend.spend_date = attributed_daily.order_date
    and spend.channel = attributed_daily.attributed_channel
