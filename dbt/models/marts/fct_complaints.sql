{{ config(indexes=[{'columns': ['company_key', 'date_received']}]) }}

-- Fact table: one row per complaint, with keys pointing to each dimension.
select
    s.complaint_id,
    md5(s.company_name)                                   as company_key,
    md5(s.product)                                        as product_key,
    s.date_received                                       as date_key,
    s.date_received,
    s.date_sent_to_company,
    s.date_sent_to_company - s.date_received              as days_to_forward,
    s.state,
    s.submitted_via,
    s.company_response,
    s.is_timely,
    (s.narrative is not null)                             as has_narrative
from {{ ref('stg_complaints') }} s
