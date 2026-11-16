from datetime import date

from pipeline.validate import validate

TODAY = date(2026, 11, 15)


def row(cid, received="2026-10-01T12:00:00-05:00"):
    return {"complaint_id": cid, "date_received": received}


def test_each_rejection_reason():
    rows = [row("1"), row(None), row("2", None), row("3", "not-a-date"),
            row("4", "2027-01-01"), row("1")]
    valid, rejected = validate(rows, today=TODAY)
    assert [r["complaint_id"] for r in valid] == ["1"]
    assert [r["reason"] for r in rejected] == [
        "missing_complaint_id", "missing_date_received", "invalid_date_received",
        "future_date_received", "duplicate_in_batch"]


def test_rejected_rows_keep_original_data():
    _, rejected = validate([row("9", "garbage")], today=TODAY)
    assert rejected[0]["row"]["date_received"] == "garbage"
