-- Analysis queries on the star schema. Each one answers a business question a
-- bank's complaints or risk team would actually ask.

-- 1. Which companies' complaint volume is growing fastest? (month-over-month, window function)
with monthly as (
    select c.company_name, date_trunc('month', f.date_received) as month, count(*) as complaints
    from marts.fct_complaints f
    join marts.dim_company c using (company_key)
    group by 1, 2
)
select company_name, month, complaints,
       complaints - lag(complaints) over (partition by company_name order by month) as change_vs_prev_month
from monthly
order by month desc, change_vs_prev_month desc nulls last
limit 20;

-- 2. Timely-response rate by company, ranked (CTE + DENSE_RANK: tied companies share a rank, no gaps)
with rates as (
    select c.company_name, count(*) as complaints,
           round(100.0 * avg(case when f.is_timely then 1 else 0 end), 1) as pct_timely
    from marts.fct_complaints f
    join marts.dim_company c using (company_key)
    group by 1
    having count(*) >= 50          -- ignore companies with too few complaints to judge
)
select *, dense_rank() over (order by pct_timely asc) as worst_rank
from rates
order by worst_rank;

-- 3. Share of each product's complaints closed with monetary relief
select p.product, count(*) as complaints,
       round(100.0 * avg(case when f.company_response = 'Closed with monetary relief' then 1 else 0 end), 1) as pct_monetary_relief
from marts.fct_complaints f
join marts.dim_product p using (product_key)
group by 1
order by pct_monetary_relief desc;

-- 4. Rolling 30-day complaint count per product (RANGE window over dates)
-- RANGE counts calendar days, so a day with no complaints doesn't stretch the window
-- the way "ROWS BETWEEN 29 PRECEDING" would.
with daily as (
    select p.product, f.date_received as day, count(*) as complaints
    from marts.fct_complaints f
    join marts.dim_product p using (product_key)
    group by 1, 2
)
select product, day, complaints,
       sum(complaints) over (partition by product order by day
                             range between interval '29 days' preceding and current row) as rolling_30d
from daily
order by product, day;

-- 5. Complaints by state per weekday vs weekend (join to the date dimension)
select f.state, d.is_weekend, count(*) as complaints
from marts.fct_complaints f
join marts.dim_date d on d.date_key = f.date_key
where f.state is not null
group by 1, 2
order by complaints desc
limit 20;
