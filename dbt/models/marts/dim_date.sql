-- One row per calendar day across the range of the data, so days with zero
-- complaints still show up in trend charts.
with bounds as (
    select min(date_received) as lo, max(date_received) as hi
    from {{ ref('stg_complaints') }}
)
select
    cast(d as date)                          as date_key,
    extract(year from d)::int                as year,
    extract(quarter from d)::int             as quarter,
    extract(month from d)::int               as month,
    to_char(d, 'Mon')                        as month_name,
    extract(isodow from d)::int              as day_of_week,
    extract(isodow from d) in (6, 7)         as is_weekend
from bounds, generate_series(bounds.lo, bounds.hi, interval '1 day') as d
