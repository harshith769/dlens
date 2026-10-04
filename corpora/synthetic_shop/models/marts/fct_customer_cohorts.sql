select
    date_trunc('month', customers.signup_at) as cohort_month,
    date_trunc('month', orders.order_date) as order_month,
    date_diff(
        'month',
        date_trunc('month', customers.signup_at),
        date_trunc('month', orders.order_date)
    ) as months_since_signup,
    count(distinct orders.customer_id) as cohort_customers,
    count(distinct orders.customer_id)
        filter (where orders.previous_order_date is not null) as repeat_customers,
    sum(orders.net_paid_usd) as cohort_net_paid,
    sum(sum(orders.net_paid_usd)) over (
        partition by date_trunc('month', customers.signup_at)
        order by date_trunc('month', orders.order_date)
    ) as cumulative_net_paid
from {{ ref('fct_orders') }} as orders
inner join {{ ref('dim_customers') }} as customers
    on orders.customer_id = customers.customer_id
group by date_trunc('month', customers.signup_at), date_trunc('month', orders.order_date)
