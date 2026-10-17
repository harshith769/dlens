{{ config(materialized='view') }}

-- eph_pkg: a package model; dbt records its path relative to the package.
select
    customer_id,
    upper(full_name) as name_upper
from {{ ref('stg_customers') }}
where customer_id is not null
