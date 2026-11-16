"""Validate rows before loading. Bad rows are quarantined, not silently dropped.

A row is rejected if:
- it has no complaint_id (can't be stored or deduplicated without one)
- date_received is missing, unparseable, or in the future
- its complaint_id already appeared earlier in the same batch (duplicate)

Each rejected row keeps its full original data plus a reason, so someone can
look at raw.complaints_rejected later and see exactly what was wrong.
"""
from datetime import date


def _parse_date(value):
    if not value:
        return None
    try:
        return date.fromisoformat(str(value)[:10])
    except ValueError:
        return None


def validate(rows: list[dict], today: date | None = None) -> tuple[list[dict], list[dict]]:
    """Return (valid_rows, rejected) where each rejected item is {row, reason}."""
    today = today or date.today()
    valid, rejected, seen = [], [], set()
    for row in rows:
        cid = row.get("complaint_id")
        received = _parse_date(row.get("date_received"))
        if not cid:
            reason = "missing_complaint_id"
        elif row.get("date_received") in (None, ""):
            reason = "missing_date_received"
        elif received is None:
            reason = "invalid_date_received"
        elif received > today:
            reason = "future_date_received"
        elif cid in seen:
            reason = "duplicate_in_batch"
        else:
            seen.add(cid)
            valid.append(row)
            continue
        rejected.append({"row": row, "reason": reason})
    return valid, rejected
