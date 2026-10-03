select e.id, e.name as employee, mgr.name as manager
from db.main.employees as e left join db.main.employees as mgr on e.manager_id = mgr.id
