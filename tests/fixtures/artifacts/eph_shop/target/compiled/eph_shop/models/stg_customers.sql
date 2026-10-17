select
    id as customer_id,
    first_name || ' ' || last_name as full_name
from "eph_shop"."main"."raw_customers"