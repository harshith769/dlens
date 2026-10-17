

-- eph_pkg: a package model; dbt records its path relative to the package.
select
    customer_id,
    upper(full_name) as name_upper
from "eph_shop"."main"."stg_customers"
where customer_id is not null