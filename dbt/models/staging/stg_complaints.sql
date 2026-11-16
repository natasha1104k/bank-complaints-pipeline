-- Clean and type the raw data. One row per complaint.
select
    complaint_id,
    cast(left(date_received, 10) as date)                 as date_received,
    cast(left(date_sent_to_company, 10) as date)          as date_sent_to_company,
    trim(product)                                          as product,
    nullif(trim(sub_product), '')                          as sub_product,
    nullif(trim(issue), '')                                as issue,
    trim(company)                                          as company_name,
    nullif(upper(trim(state)), '')                         as state,
    submitted_via,
    company_response,
    (timely = 'Yes')                                       as is_timely,
    nullif(trim(complaint_what_happened), '')              as narrative,
    tags,
    loaded_at
from {{ source('raw', 'complaints') }}
where complaint_id is not null
