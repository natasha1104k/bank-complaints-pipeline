# Bank Complaint Analytics Pipeline

An automated data pipeline that pulls consumer complaints about banks and other financial companies from the U.S. Consumer Financial Protection Bureau (CFPB) public API, loads them into PostgreSQL, models them into a star schema with dbt, runs data quality tests, and trains a classifier that predicts which complaints will end with money returned to the consumer. Airflow runs the pipeline daily; GitHub Actions runs the tests on every push.

```
CFPB API ──► Python extract (retries, pagination) ──► validate ──► raw.complaints (Postgres, upsert)
                                                           └──► raw.complaints_rejected (quarantine + reason)
                                       every run logged in raw.pipeline_runs (status, row counts, errors)
                                                          │
                                         dbt: staging.stg_complaints (clean + type)
                                                          │
                       marts: fct_complaints ── dim_company / dim_product / dim_date
                                                          │
                          19 dbt data tests · SQL analysis · payout classifier (logistic regression)
Airflow (Docker) schedules extract → dbt daily · GitHub Actions runs tests on every push
```

## Project layout

| Path | What it does |
|---|---|
| `pipeline/extract.py` | Calls the CFPB API page by page with search_after bookmarks; retries rate limits and server errors with exponential backoff, fails fast on bad requests |
| `pipeline/validate.py` | Checks each row; missing IDs, bad or future dates, and duplicates go to quarantine with a reason |
| `pipeline/load.py` | Upserts valid rows into `raw.complaints`, writes rejects to `raw.complaints_rejected`, logs every run in `raw.pipeline_runs` |
| `pipeline/run.py` | Command-line entry point (`--start`, `--end`, or `--sample` for offline) |
| `dbt/models/staging` | Cleans and types the raw data |
| `dbt/models/marts` | Star schema: one fact table, three dimensions, index on (company, date) |
| `dbt/tests` + `schema.yml` | 19 data tests: uniqueness, nulls, foreign keys, allowed values, date sanity |
| `sql/analysis_queries.sql` | Business questions using CTEs, LAG, DENSE_RANK, and rolling 30-day windows |
| `sql/index_benchmark.sql` | Before/after query timing for the index |
| `airflow/dags/` | Daily DAG: extract_load → dbt_build |
| `ml/train_classifier.py` | Predicts which complaints end in monetary relief from facts known at intake; reports ROC AUC, average precision, and top-10% capture vs random |
| `tests/` | Unit tests (fake API, no internet needed) + synthetic sample data |
| `.github/workflows/ci.yml` | CI: unit tests, load sample, dbt build against a throwaway Postgres |

## Run it locally

You need Python 3.11+, Docker Desktop, and Git.

```bash
# 1. Set up
cp .env.example .env              # then open .env and set a real password
python -m venv .venv
source .venv/bin/activate         # Windows: .venv\Scripts\activate
pip install -r requirements.txt joblib

# 2. Start Postgres + Airflow
docker compose up -d --build

# 3. Load real data (env vars from .env)
set -a; source .env; set +a       # Windows PowerShell: see note below
python -m pipeline.run --start 2026-01-01 --end 2026-10-31

# 4. Build the warehouse and run all 19 data tests
cd dbt && dbt build --profiles-dir . && cd ..

# 5. Analysis, index benchmark, classifier
psql -h localhost -U pipeline -d complaints -f sql/analysis_queries.sql
psql -h localhost -U pipeline -d complaints -f sql/index_benchmark.sql
python -m ml.train_classifier

# 6. Airflow UI: http://localhost:8080
#    Username "admin"; password is in: docker compose logs airflow | grep -i password
#    Turn on the cfpb_complaints_daily DAG.
```

Windows PowerShell, instead of `set -a; source .env`:
`Get-Content .env | ForEach-Object { if ($_ -match '^([^#=]+)=(.*)$') { Set-Item "env:$($matches[1])" $matches[2] } }`

Offline test with the sample data: `python -m pipeline.run --sample tests/fixtures/sample_complaints.json`, then `pytest -q`.

The pipeline requests one day at a time and pages with the API's search_after bookmarks, because the API ignores the usual frm offset (it returned the same page repeatedly, which the duplicate check caught). A busy day has 14,000–32,000 complaints, so a month is roughly 600,000 rows.

## Getting your real resume numbers

Every number on your resume must come from your own run on the live API, not from the sample data. The sample has a pattern built in on purpose (credit cards and checking accounts get more payouts), so the classifier's sample scores mean nothing; only scores on real data count.

| Resume claim | Where to get it |
|---|---|
| Complaints ingested | `select count(*) from raw.complaints;` |
| Rows quarantined, by reason | `select reason, count(*) from raw.complaints_rejected group by 1;` |
| Successful runs logged | `select status, count(*) from raw.pipeline_runs group by 1;` |
| Companies / products covered | `select count(*) from marts.dim_company;` (and `dim_product`) |
| Data tests | dbt prints `PASS=… TOTAL=…`; 19 are tests, the rest are models |
| Consecutive daily runs | Airflow UI → DAG → Grid view (count green runs) |
| Query speedup | "Execution Time" lines from `index_benchmark.sql`, typical of 2–3 runs |
| Classifier results | `ml/artifacts/metrics.json`: `roc_auc`, `avg_precision` vs `baseline_avg_precision`, `top10_capture` vs 0.10 |
| Day-by-day reconciliation | Compare each day's API total (`hits.total.value`) with `count(*)` in `raw.complaints` |

## Design decisions (be ready to explain these)

- **Why upsert instead of insert?** The DAG re-pulls a 3-day window because the CFPB publishes some complaints late. Upsert on `complaint_id` makes overlapping loads safe and makes reruns idempotent.
- **Why retry 429/5xx but not 400?** Rate limits and server errors are temporary; a 400 means the request itself is wrong, so retrying just wastes time. A unit test checks each case.
- **Why quarantine bad rows instead of dropping them?** Dropped rows vanish without a trace. Quarantined rows keep their original data and a reason, so you can count them, investigate them, and fix the cause.
- **Why log every run?** If the numbers look off on Tuesday, `raw.pipeline_runs` shows which run loaded what, whether it failed, and why. That's what "auditable" means.
- **Why DENSE_RANK rather than RANK?** With ties, RANK skips numbers (1, 1, 3); DENSE_RANK doesn't (1, 1, 2), which reads better in a "worst companies" list.
- **Why a RANGE window for the 30-day count?** RANGE counts calendar days. ROWS BETWEEN 29 PRECEDING counts rows, so if some days have no complaints, the window would quietly stretch past 30 days.
- **Why a star schema?** Analysts ask "complaints by company, by product, by month." One narrow fact table joined to small dimensions makes those questions simple and fast.
- **Why a date dimension?** So days or months with zero complaints still appear in trends instead of silently disappearing.
- **Why index (company_key, date_received)?** The most common filter is one company over a date range. A composite index in that order serves exactly that query.
- **Why is one data test a warning?** "Sent before received" is a real data anomaly worth surfacing, not a reason to stop the whole pipeline.
- **Why predict payouts instead of reading complaint text?** The CFPB no longer publishes narratives: in November 2026, neither the API nor the bulk download file included them. Predicting monetary relief from intake facts is also directly useful: a complaints team could review likely-costly complaints first.
- **Why leave out timely response and the company's public response?** They're decided after the complaint arrives. Using future information is leakage and makes a model look better than it would be in real use.
- **Why not accuracy?** Payouts are rare. A model that always says "no payout" is highly accurate and useless. ROC AUC, average precision vs the payout rate, and top-10% capture vs 10% all compare the model to random.
- **Why `class_weight="balanced"`?** Without it, the model learns that "no" is almost always right and ignores payouts.
- **Why group rare companies?** A company with 3 complaints can't teach the model anything reliable; grouping companies under 20 complaints into "other" prevents memorizing noise.
- **Why does dbt run in its own virtual environment in Docker?** dbt and Airflow pin conflicting package versions; separate environments avoid that clash.
- **Where are passwords?** In `.env` (git-ignored) and environment variables. Nothing secret is committed.

Data: CFPB Consumer Complaint Database, public domain. Complaints are not verified by the CFPB, so counts describe complaints filed, not bank misconduct.
