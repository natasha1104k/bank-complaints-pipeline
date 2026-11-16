"""Load: write complaints into raw.complaints in PostgreSQL.

Upsert (INSERT ... ON CONFLICT) makes the load idempotent: rerunning the same
day doesn't create duplicates, and updated complaints overwrite old versions.
"""
import json

import psycopg2
from psycopg2.extras import execute_values

from pipeline.extract import FIELDS

DDL = """
CREATE SCHEMA IF NOT EXISTS raw;
CREATE TABLE IF NOT EXISTS raw.complaints (
    complaint_id            TEXT PRIMARY KEY,
    date_received           TEXT,
    date_sent_to_company    TEXT,
    product                 TEXT,
    sub_product             TEXT,
    issue                   TEXT,
    sub_issue               TEXT,
    company                 TEXT,
    state                   TEXT,
    zip_code                TEXT,
    submitted_via           TEXT,
    company_response        TEXT,
    timely                  TEXT,
    consumer_disputed       TEXT,
    complaint_what_happened TEXT,
    tags                    TEXT,
    loaded_at               TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- One row per pipeline run: what was asked for, what happened, how many rows.
CREATE TABLE IF NOT EXISTS raw.pipeline_runs (
    run_id         BIGSERIAL PRIMARY KEY,
    started_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
    finished_at    TIMESTAMPTZ,
    source         TEXT NOT NULL,           -- 'api' or 'sample'
    window_start   DATE,
    window_end     DATE,
    status         TEXT NOT NULL DEFAULT 'running',   -- running / success / failed
    rows_fetched   INT,
    rows_loaded    INT,
    rows_rejected  INT,
    error_message  TEXT
);

-- Quarantine: rows that failed validation, with the reason and the original data.
CREATE TABLE IF NOT EXISTS raw.complaints_rejected (
    rejection_id   BIGSERIAL PRIMARY KEY,
    run_id         BIGINT REFERENCES raw.pipeline_runs (run_id),
    complaint_id   TEXT,
    reason         TEXT NOT NULL,
    payload        JSONB NOT NULL,
    rejected_at    TIMESTAMPTZ NOT NULL DEFAULT now()
);
"""


def ensure_table(conn) -> None:
    with conn.cursor() as cur:
        cur.execute(DDL)
    conn.commit()


def start_run(conn, source: str, window_start=None, window_end=None) -> int:
    with conn.cursor() as cur:
        cur.execute("INSERT INTO raw.pipeline_runs (source, window_start, window_end) "
                    "VALUES (%s, %s, %s) RETURNING run_id", (source, window_start, window_end))
        run_id = cur.fetchone()[0]
    conn.commit()
    return run_id


def finish_run(conn, run_id: int, status: str, fetched=None, loaded=None, rejected=None, error=None):
    conn.rollback()   # clear any failed transaction so the log write itself succeeds
    with conn.cursor() as cur:
        cur.execute("UPDATE raw.pipeline_runs SET finished_at = now(), status = %s, rows_fetched = %s, "
                    "rows_loaded = %s, rows_rejected = %s, error_message = %s WHERE run_id = %s",
                    (status, fetched, loaded, rejected, error, run_id))
    conn.commit()


def quarantine(conn, run_id: int, rejected: list[dict]) -> int:
    if not rejected:
        return 0
    values = [(run_id, r["row"].get("complaint_id"), r["reason"], json.dumps(r["row"], default=str))
              for r in rejected]
    with conn.cursor() as cur:
        execute_values(cur, "INSERT INTO raw.complaints_rejected (run_id, complaint_id, reason, payload) "
                            "VALUES %s", values)
    conn.commit()
    return len(values)


def upsert(conn, rows: list[dict]) -> int:
    """Rows must already be validated (unique ids, valid dates)."""
    if not rows:
        return 0
    unique = {r["complaint_id"]: r for r in rows}
    cols = ", ".join(FIELDS)
    updates = ", ".join(f"{c} = EXCLUDED.{c}" for c in FIELDS if c != "complaint_id")
    sql = (f"INSERT INTO raw.complaints ({cols}) VALUES %s "
           f"ON CONFLICT (complaint_id) DO UPDATE SET {updates}, loaded_at = now()")
    values = [tuple(None if r[c] is None else str(r[c]) for c in FIELDS) for r in unique.values()]
    with conn.cursor() as cur:
        execute_values(cur, sql, values, page_size=1000)
    conn.commit()
    return len(values)


def connect(settings: dict):
    return psycopg2.connect(**settings)
