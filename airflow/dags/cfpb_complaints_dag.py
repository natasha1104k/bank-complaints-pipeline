"""Daily pipeline: pull yesterday's complaints, then rebuild and test the warehouse.

extract_load  ->  dbt_build
If extract_load fails (e.g. the API is down after all retries), dbt_build doesn't run,
so the warehouse never gets rebuilt from a partial load.
"""
from datetime import datetime, timedelta

from airflow import DAG
from airflow.operators.bash import BashOperator
from airflow.operators.python import PythonOperator

PROJECT = "/opt/airflow/project"


def _extract_load(data_interval_start, data_interval_end, **_):
    from pipeline.run import main
    # Re-pull a 3-day window: the CFPB publishes some complaints a few days late,
    # and the upsert makes overlapping loads safe.
    start = (data_interval_start - timedelta(days=2)).date().isoformat()
    end = data_interval_end.date().isoformat()
    loaded = main(["--start", start, "--end", end])
    if loaded == 0:
        print("No complaints in window; nothing new to load.")


with DAG(
    dag_id="cfpb_complaints_daily",
    start_date=datetime(2026, 1, 1),
    schedule="@daily",
    catchup=False,
    default_args={"retries": 2, "retry_delay": timedelta(minutes=10)},
    tags=["cfpb", "portfolio"],
) as dag:
    extract_load = PythonOperator(task_id="extract_load", python_callable=_extract_load)

    dbt_build = BashOperator(
        task_id="dbt_build",
        bash_command=(
            f"cd {PROJECT}/dbt && /opt/dbt_venv/bin/dbt build --profiles-dir . "
            "--target-path /tmp/dbt_target --log-path /tmp/dbt_logs"
        ),
    )

    extract_load >> dbt_build
