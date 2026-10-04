with base as (
  select
    o.id,
    o.amt - (select max(r.refund_amt) from db.main.refunds as r) as d
  from db.main.orders as o
)
select id, d, d * 2 as d2 from base
