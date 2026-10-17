select
    n.customer_id,
    n.name_upper as display_name
from {{ ref('pkg_customer_names') }} as n
