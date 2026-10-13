import sqlite3
import time

import pytest

from deeptutor.services.llm import usage_ledger
from deeptutor.services.llm.usage_ledger import RetentionPolicy


def _write(path, call_id, started_at, policy=None):
    usage_ledger.record_call(
        path,
        {
            "call_id": call_id,
            "model": "test-model",
            "provider": "test-provider",
            "status": "completed",
            "estimated": False,
            "prompt_tokens": 10,
            "completion_tokens": 5,
            "total_tokens": 15,
        },
        started_at=started_at,
        session_id="session",
        turn_id="turn",
        source="test",
        policy=policy,
    )


def _call_ids(path):
    return [
        record["summaries"][0]["call_details"][0]["call_id"]
        for record in usage_ledger.usage_records(0, 9999999999, path=path)
    ]


def test_env_defaults_keep_append_only_behavior(monkeypatch, tmp_path):
    monkeypatch.delenv(usage_ledger.MAX_ROWS_ENV, raising=False)
    monkeypatch.delenv(usage_ledger.MAX_AGE_DAYS_ENV, raising=False)
    assert RetentionPolicy.from_env() == RetentionPolicy()
    assert not RetentionPolicy.from_env().active
    path = tmp_path / "usage.sqlite3"
    for index in range(5):
        _write(path, f"c{index}", 1000.0 + index)
    assert _call_ids(path) == [f"c{index}" for index in range(5)]
    assert usage_ledger.enforce_retention(path) == 0
    assert _call_ids(path) == [f"c{index}" for index in range(5)]


@pytest.mark.parametrize(
    ("rows", "age_days"),
    [("0", "0"), ("-3", ""), ("abc", "-1"), ("", "nan"), ("nan", "inf"), ("inf", "1e400")],
)
def test_non_positive_or_invalid_env_values_disable_retention(monkeypatch, rows, age_days):
    monkeypatch.setenv(usage_ledger.MAX_ROWS_ENV, rows)
    monkeypatch.setenv(usage_ledger.MAX_AGE_DAYS_ENV, age_days)
    assert not RetentionPolicy.from_env().active


def test_invalid_rows_env_keeps_the_valid_age_rule(monkeypatch):
    monkeypatch.setenv(usage_ledger.MAX_ROWS_ENV, "abc")
    monkeypatch.setenv(usage_ledger.MAX_AGE_DAYS_ENV, "7")
    policy = RetentionPolicy.from_env()
    assert policy.max_rows is None
    assert policy.max_age_seconds == pytest.approx(604800.0)


def test_env_values_parse_to_limits(monkeypatch):
    monkeypatch.setenv(usage_ledger.MAX_ROWS_ENV, "500")
    monkeypatch.setenv(usage_ledger.MAX_AGE_DAYS_ENV, "0.5")
    policy = RetentionPolicy.from_env()
    assert policy.max_rows == 500
    assert policy.max_age_seconds == pytest.approx(43200.0)
    assert policy.active


def test_max_rows_trims_oldest_rows_on_write(monkeypatch, tmp_path):
    monkeypatch.setenv(usage_ledger.MAX_ROWS_ENV, "3")
    path = tmp_path / "usage.sqlite3"
    for index in range(5):
        _write(path, f"c{index}", 2000.0 + index)
    assert _call_ids(path) == ["c2", "c3", "c4"]


def test_max_age_drops_stale_rows_on_write(tmp_path):
    path = tmp_path / "usage.sqlite3"
    now = time.time()
    policy = RetentionPolicy(max_age_seconds=3600)
    _write(path, "stale", now - 7200, policy)
    _write(path, "fresh", now - 60, policy)
    assert _call_ids(path) == ["fresh"]


def test_maintenance_entry_boundary_and_counts(tmp_path):
    path = tmp_path / "usage.sqlite3"
    now = 1_800_000_000.0
    for index, age in enumerate((7200, 3600, 3599, 0)):
        _write(path, f"c{index}", now - age)
    removed = usage_ledger.enforce_retention(
        path, policy=RetentionPolicy(max_age_seconds=3600), now=now
    )
    assert removed == 1
    assert _call_ids(path) == ["c1", "c2", "c3"]
    assert (
        usage_ledger.enforce_retention(path, policy=RetentionPolicy(max_age_seconds=3600), now=now)
        == 0
    )


def test_single_run_delete_cap_bounds_work_and_makes_progress(monkeypatch, tmp_path):
    monkeypatch.setattr(usage_ledger, "_RETENTION_MAX_DELETE_PER_RUN", 2)
    path = tmp_path / "usage.sqlite3"
    for index in range(5):
        _write(path, f"c{index}", 3000.0 + index)
    policy = RetentionPolicy(max_rows=1)
    assert usage_ledger.enforce_retention(path, policy=policy) == 2
    assert _call_ids(path) == ["c2", "c3", "c4"]
    assert usage_ledger.enforce_retention(path, policy=policy) == 2
    assert _call_ids(path) == ["c4"]
    assert usage_ledger.enforce_retention(path, policy=policy) == 0
    assert _call_ids(path) == ["c4"]


def test_maintenance_on_missing_database_is_noop(tmp_path):
    path = tmp_path / "absent.sqlite3"
    assert usage_ledger.enforce_retention(path, policy=RetentionPolicy(max_rows=1)) == 0
    assert not path.exists()


def test_retention_failure_never_breaks_the_write(monkeypatch, tmp_path):
    def boom(*args, **kwargs):
        raise sqlite3.OperationalError("database is locked")

    monkeypatch.setattr(usage_ledger, "_enforce_retention", boom)
    path = tmp_path / "usage.sqlite3"
    _write(path, "c0", 4000.0, RetentionPolicy(max_rows=1))
    assert _call_ids(path) == ["c0"]


def test_trimmed_ledger_still_feeds_the_read_path(tmp_path):
    from deeptutor.services.session.usage_statistics import aggregate_usage

    path = tmp_path / "usage.sqlite3"
    base = 1_700_000_000.0
    for index in range(4):
        _write(path, f"c{index}", base + index)
    assert usage_ledger.enforce_retention(path, policy=RetentionPolicy(max_rows=2)) == 2
    records = usage_ledger.usage_records(0, 9999999999, path=path)
    assert [r["summaries"][0]["call_details"][0]["call_id"] for r in records] == ["c2", "c3"]
    result = aggregate_usage(records, year=2023, timezone="UTC")
    assert result.totals.total_calls == 2
    assert result.totals.total_tokens == 30
