select
    revenue_monthly.finance_month,
    revenue_monthly.revenue_finance,
    revenue_monthly.revenue_marketing,
    revenue_monthly.refunded_amount,
    margins_monthly.net_revenue,
    margins_monthly.contribution_margin,
    adjustments_monthly.adjustments_total,
    revenue_monthly.revenue_finance_mom_change
from (
    select
        date_trunc('month', order_date) as finance_month,
        sum(revenue_finance) as revenue_finance,
        sum(revenue_marketing) as revenue_marketing,
        sum(refunded_amount) as refunded_amount,
        sum(revenue_finance) - lag(sum(revenue_finance)) over (
            order by date_trunc('month', order_date)
        ) as revenue_finance_mom_change
    from {{ ref('fct_daily_revenue') }}
    group by date_trunc('month', order_date)
) as revenue_monthly
inner join (
    select
        date_trunc('month', order_date) as margin_month,
        sum(net_revenue) as net_revenue,
        sum(contribution_margin) as contribution_margin
    from {{ ref('fct_order_margins') }}
    group by date_trunc('month', order_date)
) as margins_monthly
    on revenue_monthly.finance_month = margins_monthly.margin_month
left join (
    select
        date_trunc('month', orders.order_date) as adjustment_month,
        sum(adjustments.adjustment_amount_usd) as adjustments_total
    from {{ ref('int_order_adjustments') }} as adjustments
    inner join {{ ref('fct_orders') }} as orders
        on adjustments.order_id = orders.order_id
    group by date_trunc('month', orders.order_date)
) as adjustments_monthly
    on revenue_monthly.finance_month = adjustments_monthly.adjustment_month
