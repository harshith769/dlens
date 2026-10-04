with rfm_base as (
    select
        customers.customer_id,
        customers.order_count,
        customers.lifetime_value,
        date_diff(
            'day',
            customers.most_recent_order_date,
            (select max(order_date) from {{ ref('fct_orders') }})
        ) as recency_days,
        coalesce(sessions.session_count, 0) as web_session_count
    from {{ ref('dim_customers') }} as customers
    left join {{ ref('int_customer_sessions') }} as sessions
        on customers.customer_id = sessions.customer_id
),

rfm_scores as (
    select
        customer_id,
        recency_days,
        case
            when recency_days <= 30 then 3
            when recency_days <= 90 then 2
            else 1
        end as rfm_recency_score,
        case
            when order_count >= 4 then 3
            when order_count >= 2 then 2
            else 1
        end as rfm_frequency_score,
        case
            when lifetime_value >= 500 then 3
            when lifetime_value >= 150 then 2
            else 1
        end as rfm_monetary_score,
        web_session_count
    from rfm_base
)

select
    customer_id,
    recency_days,
    rfm_recency_score,
    rfm_frequency_score,
    rfm_monetary_score,
    rfm_recency_score * 100 + rfm_frequency_score * 10 + rfm_monetary_score as rfm_score,
    web_session_count
from rfm_scores
