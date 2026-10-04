select
    user_id,
    count(id) filter (where status = 'late') as late_n,
    sum(case when status = 'late' then 1 else 0 end) as late_n_case
from db.main.orders
group by user_id
