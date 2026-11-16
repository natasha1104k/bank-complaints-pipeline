"""Settings read from environment variables, so no passwords live in the code."""
import os

API_URL = "https://www.consumerfinance.gov/data-research/consumer-complaints/search/api/v1/"
PAGE_SIZE = 1000          # rows per API request
MAX_RETRIES = 5           # attempts before giving up on one request
BACKOFF_SECONDS = 2       # wait 2s, 4s, 8s... between retries


def db_settings() -> dict:
    return {
        "host": os.getenv("WAREHOUSE_HOST", "localhost"),
        "port": int(os.getenv("WAREHOUSE_PORT", "5432")),
        "dbname": os.getenv("WAREHOUSE_DB", "complaints"),
        "user": os.getenv("WAREHOUSE_USER", "pipeline"),
        "password": os.getenv("WAREHOUSE_PASSWORD", ""),
    }

# Safety valve: stop after this many rows for one search (one day), so a bug
# in paging can never loop forever. Real days have been 14,000-32,000 rows.
MAX_RESULTS = 200_000
