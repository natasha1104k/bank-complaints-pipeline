"""Unit tests for extraction. They use a fake session, so no internet is needed."""
from datetime import date

import pytest
import requests

from pipeline import config, extract


class FakeResponse:
    def __init__(self, status, payload=None):
        self.status_code, self._payload = status, payload

    def json(self):
        return self._payload

    def raise_for_status(self):
        if self.status_code >= 400:
            raise requests.HTTPError(str(self.status_code))


class FakeSession:
    def __init__(self, responses):
        self.responses, self.calls = list(responses), []

    def get(self, url, params=None, timeout=None):
        self.calls.append(params)
        return self.responses.pop(0)


def page(n, start=0):
    """A fake API page of n complaints; each carries sort values like the real API."""
    return {"hits": {"hits": [{"_id": str(start + i), "sort": [1000 - start - i, str(start + i)],
                               "_source": {"complaint_id": start + i, "tags": ["Servicemember"]}}
                              for i in range(n)]}}


@pytest.fixture(autouse=True)
def no_sleep(monkeypatch):
    monkeypatch.setattr(extract.time, "sleep", lambda s: None)


def test_paginates_with_bookmarks_until_short_page():
    s = FakeSession([FakeResponse(200, page(2)), FakeResponse(200, page(2, 2)), FakeResponse(200, page(1, 4))])
    rows = extract.fetch_complaints(date(2026, 1, 1), date(2026, 1, 2), session=s, page_size=2)
    assert [r["complaint_id"] for r in rows] == ["0", "1", "2", "3", "4"]
    # page 1 has no bookmark; each later page continues after the previous page's last complaint
    assert [c.get("search_after") for c in s.calls] == [None, "999_1", "997_3"]
    assert all(c["frm"] == 0 for c in s.calls)


def test_retries_then_succeeds():
    s = FakeSession([FakeResponse(503), FakeResponse(429), FakeResponse(200, page(1))])
    rows = extract.fetch_complaints(date(2026, 1, 1), date(2026, 1, 2), session=s, page_size=10)
    assert len(rows) == 1 and len(s.calls) == 3


def test_gives_up_after_max_retries():
    s = FakeSession([FakeResponse(500)] * config.MAX_RETRIES)
    with pytest.raises(requests.HTTPError):
        extract.fetch_complaints(date(2026, 1, 1), date(2026, 1, 2), session=s)


def test_client_error_is_not_retried():
    s = FakeSession([FakeResponse(400)])
    with pytest.raises(requests.HTTPError):
        extract.fetch_complaints(date(2026, 1, 1), date(2026, 1, 2), session=s)
    assert len(s.calls) == 1


def test_flatten_joins_tags_and_stringifies_id():
    row = extract._flatten({"_id": "7", "_source": {"complaint_id": 7, "tags": ["Older American", "Servicemember"]}})
    assert row["complaint_id"] == "7"
    assert row["tags"] == "Older American, Servicemember"
    assert set(row) == set(extract.FIELDS)


def test_stops_at_safety_limit(monkeypatch):
    monkeypatch.setattr(config, "MAX_RESULTS", 4)
    s = FakeSession([FakeResponse(200, page(2)), FakeResponse(200, page(2, 2))])
    rows = extract.fetch_complaints(date(2026, 1, 1), date(2026, 1, 1), session=s, page_size=2)
    assert len(rows) == 4 and len(s.calls) == 2   # never asks for more


def test_stops_if_bookmark_does_not_move():
    same = page(2)
    s = FakeSession([FakeResponse(200, same), FakeResponse(200, same)])
    rows = extract.fetch_complaints(date(2026, 1, 1), date(2026, 1, 1), session=s, page_size=2)
    assert len(s.calls) == 2 and len(rows) == 4   # the duplicates get caught by validation later


def test_run_fetches_one_day_at_a_time():
    from pipeline.run import days_between
    assert [d.day for d in days_between(date(2026, 10, 30), date(2026, 11, 2))] == [30, 31, 1, 2]
