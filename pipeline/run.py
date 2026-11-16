"""Command-line entry point: extract a date range day by day, validate, load, and log the run.

    python -m pipeline.run --start 2026-10-01 --end 2026-10-31
    python -m pipeline.run --sample tests/fixtures/sample_complaints.json   # offline

We ask for one day at a time and load each day as soon as it arrives. If day 20
fails, days 1-19 are already saved, and rerunning is safe because the load is an
upsert. (A busy day has 14,000-32,000 complaints.)

Every run gets a row in raw.pipeline_runs (success or failure, with row counts),
and rows that fail validation go to raw.complaints_rejected with a reason.
"""
import argparse
import json
import logging
from collections import Counter
from datetime import date, timedelta

from pipeline import config, extract, load, validate

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("pipeline")


def days_between(start: date, end: date):
    day = start
    while day <= end:
        yield day
        day += timedelta(days=1)


def main(argv=None) -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--start", type=date.fromisoformat, default=date.today() - timedelta(days=7))
    p.add_argument("--end", type=date.fromisoformat, default=date.today())
    p.add_argument("--sample", help="load a local JSON file instead of calling the API")
    args = p.parse_args(argv)

    fetched = loaded = rejected_count = 0
    reasons = Counter()
    conn = load.connect(config.db_settings())
    try:
        load.ensure_table(conn)
        if args.sample:
            run_id = load.start_run(conn, "sample")
        else:
            run_id = load.start_run(conn, "api", args.start, args.end)
        try:
            if args.sample:
                with open(args.sample) as f:
                    batches = [[extract._flatten(h) for h in json.load(f)]]
            else:
                # A generator: each day is fetched only when the loop reaches it.
                batches = (extract.fetch_complaints(d, d) for d in days_between(args.start, args.end))
            for rows in batches:
                valid, rejected = validate.validate(rows)
                loaded += load.upsert(conn, valid)
                load.quarantine(conn, run_id, rejected)
                fetched += len(rows)
                rejected_count += len(rejected)
                reasons.update(r["reason"] for r in rejected)
        except Exception as exc:
            load.finish_run(conn, run_id, "failed", fetched, loaded, rejected_count, str(exc)[:1000])
            log.exception("Run %s failed after loading %s rows", run_id, loaded)
            raise
        load.finish_run(conn, run_id, "success", fetched, loaded, rejected_count)
        log.info("Run %s: fetched %s, loaded %s, rejected %s %s",
                 run_id, fetched, loaded, rejected_count, dict(reasons))
        return loaded
    finally:
        conn.close()


if __name__ == "__main__":
    main()
