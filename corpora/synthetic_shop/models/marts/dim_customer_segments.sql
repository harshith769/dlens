select
    customer_id,
    rfm_score,
    recency_days,
    case
        when rfm_score >= 330 then 'champion'
        when rfm_recency_score = 1 then 'hibernating'
        when rfm_score >= 220 then 'loyal'
        else 'at_risk'
    end as customer_segment,
    rfm_monetary_score = 3 as is_high_value
from {{ ref('dim_customer_rfm') }}
