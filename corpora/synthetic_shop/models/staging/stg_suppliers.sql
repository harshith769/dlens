select
    id as supplier_id,
    name as supplier_name,
    upper(country) as supplier_country,
    lead_time_days
from {{ ref('raw_suppliers') }}
