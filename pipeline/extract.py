"""Extract: pull complaints from the CFPB public API.

What makes this robust:
- Retries with exponential backoff: if the API times out or returns a 5xx/429,
  wait and try again instead of crashing the whole run. Other 4xx errors mean
  our request is wrong, so we fail immediately instead of retrying.
- Cursor ("search_after") pagination: the API ignores the usual "start at row X"
  setting (frm), and returned the same page over and over when we used it.
  Instead, each page's last complaint carries its sort values
  [timestamp, complaint_id]; we send those back as a bookmark ("give me what
  comes after this one"). This also isn't limited to 10,000 rows the way
  "start at row X" paging is.
- A safety valve (config.MAX_RESULTS) so a paging bug can never loop forever.
"""
import logging
import time
from datetime import date

import requests

from pipeline import config

log = logging.getLogger(__name__)

# Fields we keep from each complaint. Everything else in the API response is dropped.
FIELDS = [
    "complaint_id", "date_received", "date_sent_to_company", "product", "sub_product",
    "issue", "sub_issue", "company", "state", "zip_code", "submitted_via",
    "company_response", "timely", "consumer_disputed", "complaint_what_happened", "tags",
]


class RetryableError(requests.HTTPError):
    """Temporary server-side failure (rate limit or 5xx) worth trying again."""


def _get_with_retries(session: requests.Session, params: dict) -> dict:
    for attempt in range(1, config.MAX_RETRIES + 1):
        try:
            resp = session.get(config.API_URL, params=params, timeout=60)
            if resp.status_code == 429 or resp.status_code >= 500:
                raise RetryableError(f"status {resp.status_code}")
            resp.raise_for_status()   # other 4xx = our request is wrong; retrying won't help
            return resp.json()
        except (requests.ConnectionError, requests.Timeout, RetryableError) as exc:
            if attempt == config.MAX_RETRIES:
                raise
            wait = config.BACKOFF_SECONDS * 2 ** (attempt - 1)
            log.warning("Attempt %s failed (%s); retrying in %ss", attempt, exc, wait)
            time.sleep(wait)
    raise RuntimeError("unreachable")


def _flatten(hit: dict) -> dict:
    src = hit.get("_source", hit)
    row = {f: src.get(f) for f in FIELDS}
    # complaint_id sometimes only appears as the document id
    cid = row["complaint_id"] or hit.get("_id")
    row["complaint_id"] = str(cid) if cid not in (None, "") else None
    if isinstance(row["tags"], list):
        row["tags"] = ", ".join(row["tags"])
    return row


def _bookmark(hit: dict) -> str | None:
    """Turn a complaint's sort values [1790899188000, '28830795'] into '1790899188000_28830795'."""
    values = hit.get("sort")
    return "_".join(str(v) for v in values) if values else None


def fetch_complaints(start: date, end: date, session: requests.Session | None = None,
                     page_size: int = config.PAGE_SIZE) -> list[dict]:
    """Return every complaint received between start and end (inclusive)."""
    session = session or requests.Session()
    rows, after = [], None
    while True:
        params = {
            "date_received_min": start.isoformat(),
            "date_received_max": end.isoformat(),
            "size": page_size,
            "frm": 0,                      # required by the API, but paging is done by search_after
            "sort": "created_date_desc",
            "no_aggs": "true",
        }
        if after:
            params["search_after"] = after
        payload = _get_with_retries(session, params)
        hits = payload["hits"]["hits"] if isinstance(payload, dict) else payload
        rows.extend(_flatten(h) for h in hits)
        log.info("%s to %s: fetched %s rows (total so far %s)", start, end, len(hits), len(rows))
        if len(hits) < page_size:
            break                          # a short page means we've reached the end
        next_after = _bookmark(hits[-1])
        if next_after is None or next_after == after:
            log.warning("%s to %s: API gave no new bookmark; stopping at %s rows", start, end, len(rows))
            break
        after = next_after
        if len(rows) >= config.MAX_RESULTS:
            log.warning("%s to %s: hit the safety limit of %s rows; stopping", start, end, config.MAX_RESULTS)
            break
    return rows
