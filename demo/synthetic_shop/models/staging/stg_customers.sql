select
    id as customer_id,
    first_name,
    last_name,
    lower(trim(email)) as email,
    upper(country) as country_code,
    created_at as signup_at
from {{ ref('raw_customers') }}
