with __dbt__cte__base as (
    select id, amt, status from db.main.orders
),  __dbt__cte__big as (
    select id, amt from __dbt__cte__base where amt > 100
)
select big.id, sum(big.amt) as total_amt
from __dbt__cte__big as big
group by big.id
