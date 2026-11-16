FROM apache/airflow:2.10.5-python3.11

# Switch to the administrator just long enough to create dbt's folder
# and give it to the airflow user (the image normally runs as "airflow").
USER root
RUN mkdir -p /opt/dbt_venv && chown airflow:root /opt/dbt_venv
USER airflow

# dbt gets its own virtual environment so its packages can't clash with Airflow's.
RUN python -m venv /opt/dbt_venv \
 && /opt/dbt_venv/bin/pip install --no-cache-dir "dbt-core>=1.10,<1.11" "dbt-postgres>=1.9,<1.10"

RUN pip install --no-cache-dir requests psycopg2-binary
