-- A complaint can't be forwarded to the company before the CFPB received it.
-- Set to warn: the real data has a handful of these, and we want to see them, not block the run.
{{ config(severity='warn') }}
select complaint_id, date_received, date_sent_to_company
from {{ ref('fct_complaints') }}
where date_sent_to_company < date_received
