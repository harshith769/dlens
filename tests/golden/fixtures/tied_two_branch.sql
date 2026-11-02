with base as (
    select id, amt from db.main.orders
),
lhs as (
    select id, amt * 2 as amt_x from base
),
rhs as (
    select id, amt - 1 as amt_y from base
)
select lhs.id, lhs.amt_x + rhs.amt_y as amt_mix
from lhs
join rhs on lhs.id = rhs.id
