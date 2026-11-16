-- Complaints can't be received in the future; if they are, the load parsed dates wrong.
select complaint_id, date_received
from {{ ref('fct_complaints') }}
where date_received > current_date
