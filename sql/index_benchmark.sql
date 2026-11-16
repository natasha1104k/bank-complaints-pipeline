-- Measure what the index on fct_complaints (company_key, date_received) buys you.
-- dbt creates that index on every build (see the config in fct_complaints.sql).
--
-- Run with real data (tens of thousands of rows or more). On tiny data Postgres
-- ignores indexes and the numbers mean nothing.
-- Compare the "Execution Time" line of the two outputs. Run it 2-3 times and use
-- the typical value, since the first run can be slower while data is cached.

ANALYZE marts.fct_complaints;

-- BEFORE: tell Postgres not to use any index for this session
SET enable_indexscan = off;
SET enable_bitmapscan = off;
SET enable_indexonlyscan = off;

EXPLAIN ANALYZE
SELECT date_trunc('month', date_received) AS month, count(*)
FROM marts.fct_complaints
WHERE company_key = (SELECT company_key FROM marts.dim_company ORDER BY company_name LIMIT 1)
  AND date_received >= current_date - INTERVAL '365 days'
GROUP BY 1;

-- AFTER: allow the index again
RESET enable_indexscan;
RESET enable_bitmapscan;
RESET enable_indexonlyscan;

EXPLAIN ANALYZE
SELECT date_trunc('month', date_received) AS month, count(*)
FROM marts.fct_complaints
WHERE company_key = (SELECT company_key FROM marts.dim_company ORDER BY company_name LIMIT 1)
  AND date_received >= current_date - INTERVAL '365 days'
GROUP BY 1;
