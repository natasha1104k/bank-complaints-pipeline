select distinct
    md5(company_name) as company_key,
    company_name
from {{ ref('stg_complaints') }}
where company_name is not null
