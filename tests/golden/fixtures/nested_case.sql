select id,
  case when status = 'paid' then case when amt > 100 then amt else 0 end
       when status = 'open' then tax else null end as bucket
from db.main.orders
