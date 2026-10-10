"""Analytics report contract over a fully mocked storage layer.

Each test drives ``services.practice.analytics.analytics`` directly with a raw
in-memory sqlite connection that holds only the columns the report reads, so
the calendar aggregation is pinned independently of the durable stores.
"""

from datetime import datetime, timedelta, timezone
import sqlite3

import pytest

from deeptutor.services.practice.analytics import analytics

NOW = datetime(2026, 10, 10, 12, 0, tzinfo=timezone.utc).timestamp()
SCOPE = "1=1"
WINDOW_START = datetime(2026, 10, 4, 0, 0, tzinfo=timezone.utc).timestamp()
DAY = 86400


@pytest.fixture
def conn():
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.executescript(
        """
        CREATE TABLE sessions (id TEXT PRIMARY KEY, deleted_at REAL);
        CREATE TABLE notebook_entries (
            id INTEGER PRIMARY KEY,
            session_id TEXT,
            source TEXT,
            created_at REAL
        );
        CREATE TABLE practice_review_state (
            entry_id INTEGER PRIMARY KEY,
            is_mistake INTEGER NOT NULL,
            first_wrong_at REAL
        );
        CREATE TABLE practice_review_events (
            request_id TEXT PRIMARY KEY,
            entry_id INTEGER NOT NULL,
            reviewed_at REAL
        );
        """
    )
    yield conn
    conn.close()


def entry(conn, entry_id, created_at=NOW, source=None, session_id=None):
    conn.execute(
        "INSERT INTO notebook_entries(id, session_id, source, created_at) VALUES(?, ?, ?, ?)",
        (entry_id, session_id, source, created_at),
    )


def state(conn, entry_id, first_wrong_at=NOW, is_mistake=1):
    conn.execute(
        "INSERT INTO practice_review_state(entry_id, is_mistake, first_wrong_at) VALUES(?, ?, ?)",
        (entry_id, is_mistake, first_wrong_at),
    )


def review(conn, request_id, entry_id, reviewed_at=NOW):
    conn.execute(
        "INSERT INTO practice_review_events(request_id, entry_id, reviewed_at) VALUES(?, ?, ?)",
        (request_id, entry_id, reviewed_at),
    )


def report(conn, days=7, now=NOW, scope=SCOPE, params=None, timezone="UTC"):
    return analytics(conn, timezone, days, now, scope, params or [])


def day(data, date):
    return next(row for row in data["daily"] if row["date"] == date)


def test_days_must_be_7_30_or_90(conn):
    for bad in (0, 6, 8, 91, -7):
        with pytest.raises(ValueError, match="7, 30 or 90"):
            report(conn, days=bad)
    starts = {7: "2026-10-04", 30: "2026-09-11", 90: "2026-07-13"}
    for good, start in starts.items():
        data = report(conn, days=good)
        assert data["days"] == good
        assert data["start_date"] == start
        assert data["end_date"] == "2026-10-10"
        assert len(data["daily"]) == good


def test_unknown_timezone_rejected(conn):
    with pytest.raises(ValueError, match="Unknown timezone"):
        report(conn, timezone="Mars/Olympus")
    with pytest.raises(ValueError):
        report(conn, timezone="")


def test_empty_report_contract(conn):
    data = report(conn)
    assert data["timezone"] == "UTC"
    assert data["updated_at"] == NOW
    assert data["sources"] == []
    assert data["totals"] == {"questions": 0, "mistakes": 0, "reviews": 0}
    assert [row["date"] for row in data["daily"]] == [
        (datetime(2026, 10, 4, tzinfo=timezone.utc) + timedelta(days=i)).date().isoformat()
        for i in range(7)
    ]
    assert all(
        row == {"date": row["date"], "questions": 0, "mistakes": 0, "reviews": 0}
        for row in data["daily"]
    )


def test_window_edges_are_inclusive(conn):
    entry(conn, 1, created_at=WINDOW_START)
    entry(conn, 2, created_at=WINDOW_START - 0.5)
    entry(conn, 3, created_at=NOW)
    state(conn, 1, first_wrong_at=WINDOW_START)
    state(conn, 2, first_wrong_at=WINDOW_START - 0.5)
    review(conn, "r-after", 1, reviewed_at=NOW + 1)
    review(conn, "r-exact", 1, reviewed_at=NOW)
    data = report(conn)
    assert data["totals"] == {"questions": 2, "mistakes": 1, "reviews": 1}
    assert day(data, "2026-10-04") == {
        "date": "2026-10-04",
        "questions": 1,
        "mistakes": 1,
        "reviews": 0,
    }
    assert day(data, "2026-10-10")["reviews"] == 1


def test_first_wrong_before_window_is_not_a_mistake(conn):
    entry(conn, 1, created_at=NOW - 2 * DAY)
    state(conn, 1, first_wrong_at=NOW - 8 * DAY)
    data = report(conn)
    assert data["totals"] == {"questions": 1, "mistakes": 0, "reviews": 0}


def test_non_mistake_state_rows_never_count(conn):
    entry(conn, 1)
    state(conn, 1, is_mistake=0)
    data = report(conn)
    assert data["totals"] == {"questions": 1, "mistakes": 0, "reviews": 0}
    assert data["sources"][0]["mistakes"] == 0


def test_blank_source_falls_back_to_deep_question(conn):
    entry(conn, 1, source="")
    entry(conn, 2, source=None)
    entry(conn, 3, source="mastery_path")
    data = report(conn)
    assert [row["source"] for row in data["sources"]] == ["deep_question", "mastery_path"]
    assert data["sources"][0]["questions"] == 2
    assert data["sources"][1]["questions"] == 1


def test_sources_sorted_with_independent_metrics(conn):
    entry(conn, 1, source="book")
    entry(conn, 2, source="book")
    entry(conn, 3, source="book", created_at=NOW - DAY)
    entry(conn, 4, source="web")
    state(conn, 1)
    state(conn, 3, first_wrong_at=NOW - DAY)
    state(conn, 4, is_mistake=0)
    review(conn, "r1", 2)
    review(conn, "r2", 2, reviewed_at=NOW - 3600)
    review(conn, "r3", 1, reviewed_at=NOW - 2 * DAY)
    review(conn, "r4", 4)
    data = report(conn)
    assert [row["source"] for row in data["sources"]] == ["book", "web"]
    assert data["sources"][0] == {"source": "book", "questions": 3, "mistakes": 2, "reviews": 3}
    assert data["sources"][1] == {"source": "web", "questions": 1, "mistakes": 0, "reviews": 1}
    assert day(data, "2026-10-10") == {
        "date": "2026-10-10",
        "questions": 3,
        "mistakes": 1,
        "reviews": 3,
    }
    assert day(data, "2026-10-09") == {
        "date": "2026-10-09",
        "questions": 1,
        "mistakes": 1,
        "reviews": 0,
    }
    assert day(data, "2026-10-08")["reviews"] == 1
    assert data["totals"] == {"questions": 4, "mistakes": 2, "reviews": 4}


def test_scope_params_bind_before_window_bounds(conn):
    entry(conn, 1, source="book")
    entry(conn, 2, source="other")
    data = report(conn, scope="n.source = ?", params=["book"])
    assert data["totals"]["questions"] == 1
    assert [row["source"] for row in data["sources"]] == ["book"]


def test_orphan_session_rows_stay_visible(conn):
    entry(conn, 1, session_id="ghost")
    data = report(conn, scope="(n.session_id IS NULL OR s.deleted_at IS NULL)")
    assert data["totals"]["questions"] == 1


def test_null_timestamp_rows_are_dropped_not_crashing(conn):
    entry(conn, 1, created_at=None)
    state(conn, 1, first_wrong_at=None)
    review(conn, "r1", 1, reviewed_at=None)
    data = report(conn)
    assert data["totals"] == {"questions": 0, "mistakes": 0, "reviews": 0}
    assert data["sources"] == []
