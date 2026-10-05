"""Unit coverage for the practice analytics aggregation."""

from __future__ import annotations

from datetime import datetime, timezone
import sqlite3

import pytest

from deeptutor.services.practice.analytics import analytics

NOW = datetime(2026, 9, 25, 12, tzinfo=timezone.utc).timestamp()
SCOPE = "(n.session_id IS NULL OR s.deleted_at IS NULL)"

SCHEMA = """
CREATE TABLE sessions (id TEXT PRIMARY KEY, deleted_at REAL);
CREATE TABLE notebook_entries (
    id INTEGER PRIMARY KEY, session_id TEXT, source TEXT DEFAULT '', created_at REAL
);
CREATE TABLE practice_review_state (
    entry_id INTEGER PRIMARY KEY, is_mistake INTEGER DEFAULT 0, first_wrong_at REAL
);
CREATE TABLE practice_review_events (entry_id INTEGER, reviewed_at REAL);
"""


@pytest.fixture
def conn():
    connection = sqlite3.connect(":memory:")
    connection.row_factory = sqlite3.Row
    connection.executescript(SCHEMA)
    yield connection
    connection.close()


def add_question(
    conn,
    entry_id,
    created_at=NOW,
    source="",
    session_id=None,
    mistake=None,
    first_wrong_at=None,
    reviews=(),
):
    conn.execute(
        "INSERT INTO notebook_entries (id, session_id, source, created_at) VALUES (?, ?, ?, ?)",
        (entry_id, session_id, source, created_at),
    )
    if mistake is not None:
        conn.execute(
            "INSERT INTO practice_review_state (entry_id, is_mistake, first_wrong_at) VALUES (?, ?, ?)",
            (entry_id, mistake, first_wrong_at),
        )
    for reviewed_at in reviews:
        conn.execute(
            "INSERT INTO practice_review_events (entry_id, reviewed_at) VALUES (?, ?)",
            (entry_id, reviewed_at),
        )


def test_only_supported_windows_are_accepted(conn):
    for days in (7, 30, 90):
        report = analytics(conn, "UTC", days, NOW, SCOPE, [])
        assert report["days"] == days and len(report["daily"]) == days
    with pytest.raises(ValueError, match="7, 30 or 90"):
        analytics(conn, "UTC", 8, NOW, SCOPE, [])


def test_unknown_timezone_is_rejected(conn):
    with pytest.raises(ValueError, match="Unknown timezone"):
        analytics(conn, "not/a-zone", 7, NOW, SCOPE, [])


def test_window_edges_are_inclusive_and_meta_is_reported(conn):
    start_edge = datetime(2026, 9, 19, tzinfo=timezone.utc).timestamp()
    add_question(conn, 1, created_at=start_edge)
    add_question(conn, 2, created_at=start_edge - 1)
    add_question(conn, 3, created_at=NOW - 30 * 86400, reviews=(NOW,))
    report = analytics(conn, "UTC", 7, NOW, SCOPE, [])
    assert report["timezone"] == "UTC"
    assert report["start_date"] == "2026-09-19"
    assert report["end_date"] == "2026-09-25"
    assert report["updated_at"] == NOW
    assert report["totals"] == {"questions": 1, "mistakes": 0, "reviews": 1}


def test_each_metric_uses_its_own_timestamp(conn):
    add_question(
        conn,
        1,
        created_at=NOW - 3 * 86400,
        mistake=1,
        first_wrong_at=NOW - 86400,
        reviews=(NOW - 2 * 86400, NOW - 86400),
    )
    report = analytics(conn, "UTC", 7, NOW, SCOPE, [])
    by_day = {row["date"]: row for row in report["daily"]}
    assert by_day["2026-09-22"] == {
        "date": "2026-09-22",
        "questions": 1,
        "mistakes": 0,
        "reviews": 0,
    }
    assert by_day["2026-09-23"] == {
        "date": "2026-09-23",
        "questions": 0,
        "mistakes": 0,
        "reviews": 1,
    }
    assert by_day["2026-09-24"]["mistakes"] == 1 and by_day["2026-09-24"]["reviews"] == 1
    assert report["totals"] == {"questions": 1, "mistakes": 1, "reviews": 2}


def test_mistakes_keep_their_first_wrong_date_after_creation_leaves_the_window(conn):
    add_question(conn, 1, created_at=NOW - 30 * 86400, mistake=1, first_wrong_at=NOW - 86400)
    report = analytics(conn, "UTC", 7, NOW, SCOPE, [])
    assert report["totals"] == {"questions": 0, "mistakes": 1, "reviews": 0}
    assert report["daily"][-2]["mistakes"] == 1


def test_empty_source_falls_back_to_deep_question(conn):
    add_question(conn, 1, source="")
    report = analytics(conn, "UTC", 7, NOW, SCOPE, [])
    assert report["sources"] == [
        {"source": "deep_question", "questions": 1, "mistakes": 0, "reviews": 0}
    ]


def test_sources_are_grouped_per_metric_and_sorted_by_name(conn):
    add_question(conn, 1, source="mastery_path", mistake=1, first_wrong_at=NOW)
    add_question(conn, 2, source="book", reviews=(NOW,))
    add_question(conn, 3, source="book")
    report = analytics(conn, "UTC", 7, NOW, SCOPE, [])
    assert [source["source"] for source in report["sources"]] == ["book", "mastery_path"]
    assert report["sources"][0] == {"source": "book", "questions": 2, "mistakes": 0, "reviews": 1}
    assert report["sources"][1] == {
        "source": "mastery_path",
        "questions": 1,
        "mistakes": 1,
        "reviews": 0,
    }


def test_scope_and_params_restrict_every_metric(conn):
    add_question(conn, 1, session_id="s1", mistake=1, first_wrong_at=NOW, reviews=(NOW,))
    add_question(conn, 2, session_id="s2", mistake=1, first_wrong_at=NOW, reviews=(NOW,))
    report = analytics(conn, "UTC", 7, NOW, "(n.session_id IN (?))", ["s1"])
    assert report["totals"] == {"questions": 1, "mistakes": 1, "reviews": 1}
    assert analytics(conn, "UTC", 7, NOW, "1=0", [])["totals"] == {
        "questions": 0,
        "mistakes": 0,
        "reviews": 0,
    }


def test_mistake_rows_require_review_state_membership(conn):
    add_question(conn, 1, mistake=0, first_wrong_at=None)
    add_question(conn, 2)
    report = analytics(conn, "UTC", 7, NOW, SCOPE, [])
    assert report["totals"]["mistakes"] == 0


def test_local_day_bucketing_differs_from_utc(conn):
    late_evening = datetime(2026, 9, 19, 18, 30, tzinfo=timezone.utc).timestamp()
    add_question(conn, 1, created_at=late_evening)
    utc_report = analytics(conn, "UTC", 7, NOW, SCOPE, [])
    shanghai = analytics(conn, "Asia/Shanghai", 7, NOW, SCOPE, [])
    utc_day = next(row for row in utc_report["daily"] if row["questions"])
    shanghai_day = next(row for row in shanghai["daily"] if row["questions"])
    assert utc_day["date"] == "2026-09-19"
    assert shanghai_day["date"] == "2026-09-20"
    assert shanghai["start_date"] == "2026-09-19"
    assert len(shanghai["daily"]) == 7


def test_deleted_sessions_drop_out_of_the_default_scope(conn):
    add_question(conn, 1, session_id="s1", created_at=NOW - 8 * 86400)
    add_question(conn, 2, session_id="s2")
    conn.execute("INSERT INTO sessions (id, deleted_at) VALUES ('s1', NULL)")
    conn.execute("INSERT INTO sessions (id, deleted_at) VALUES ('s2', 1)")
    report = analytics(conn, "UTC", 30, NOW, SCOPE, [])
    assert report["totals"] == {"questions": 1, "mistakes": 0, "reviews": 0}
    assert [row["questions"] for row in report["daily"]].count(1) == 1
