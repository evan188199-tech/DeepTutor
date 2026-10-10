"""The built-in ``cron`` tool: schedule parsing boundaries and input rejection.

Focus: parameter parsing (at / every_seconds / cron_expr + timezone), the
register-list-cancel contract, and rejection of invalid input. The executor
layer stays out of scope here (see test_cron_tool.py's executor routing and
test_cron_executor.py); nothing in this module waits on real time — the
service is bound to a temp store and jobs are never due inside a test.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from deeptutor.services.cron.service import CronService
from deeptutor.tools.cron_tool import run_cron_action


@pytest.fixture
def cron_service(tmp_path, monkeypatch):
    import deeptutor.services.cron.service as service_mod
    import deeptutor.tools.cron_tool as tool_mod

    service = CronService(store_path=tmp_path / "jobs.sqlite3")
    monkeypatch.setattr(service_mod, "_service", service)
    monkeypatch.setattr(tool_mod, "get_cron_service", lambda: service)
    return service


CHAT_OWNER = {"kind": "chat", "user_id": "local-admin", "session_id": "s1"}


def _schedule(kwargs: dict) -> object:
    return run_cron_action({"action": "schedule", "_cron_owner": CHAT_OWNER, **kwargs})


class TestScheduleParsing:
    def test_at_naive_interpreted_as_local_time(self, cron_service):
        naive = datetime(2030, 3, 15, 9, 30)
        outcome = _schedule({"message": "ping", "at": naive.isoformat()})
        assert outcome.ok, outcome.text
        job = cron_service.get_job(outcome.meta["job_id"])
        assert job.schedule.kind == "at"
        assert job.schedule.at_ms == int(naive.astimezone().timestamp() * 1000)

    def test_at_offset_and_utc_designator_agree(self, cron_service):
        plus_two = "2030-06-01T08:00:00+02:00"
        utc_same_instant = "2030-06-01T06:00:00+00:00"
        first = _schedule({"message": "a", "at": plus_two})
        second = _schedule({"message": "b", "at": utc_same_instant})
        assert first.ok and second.ok
        job_a = cron_service.get_job(first.meta["job_id"])
        job_b = cron_service.get_job(second.meta["job_id"])
        expected = int(datetime(2030, 6, 1, 6, 0, tzinfo=timezone.utc).timestamp() * 1000)
        assert job_a.schedule.at_ms == job_b.schedule.at_ms == expected

    def test_at_unparseable_rejected(self, cron_service):
        outcome = _schedule({"message": "x", "at": "next tuesday-ish"})
        assert outcome.ok is False
        assert "could not parse time" in outcome.text
        assert "ISO 8601" in outcome.text

    def test_every_seconds_string_is_coerced(self, cron_service):
        outcome = _schedule({"message": "x", "every_seconds": "120"})
        assert outcome.ok, outcome.text
        job = cron_service.get_job(outcome.meta["job_id"])
        assert job.schedule.kind == "every"
        assert job.schedule.every_seconds == 120

    def test_every_seconds_non_numeric_rejected(self, cron_service):
        outcome = _schedule({"message": "x", "every_seconds": "often"})
        assert outcome.ok is False
        assert "Could not schedule" in outcome.text

    def test_every_below_minimum_boundary_rejected(self, cron_service):
        outcome = _schedule({"message": "x", "every_seconds": 29})
        assert outcome.ok is False
        assert "at least 30 seconds" in outcome.text

    def test_every_at_minimum_boundary_accepted(self, cron_service):
        outcome = _schedule({"message": "x", "every_seconds": 30})
        assert outcome.ok, outcome.text
        job = cron_service.get_job(outcome.meta["job_id"])
        assert job.schedule.every_seconds == 30

    def test_invalid_cron_expr_rejected(self, cron_service):
        outcome = _schedule({"message": "x", "cron_expr": "definitely not a cron"})
        assert outcome.ok is False
        assert "Could not schedule" in outcome.text

    def test_unknown_timezone_rejected(self, cron_service):
        outcome = _schedule({"message": "x", "cron_expr": "0 8 * * *", "tz": "Mars/Olympus"})
        assert outcome.ok is False
        assert "unknown timezone" in outcome.text

    def test_cron_tz_with_valid_zone_preserved(self, cron_service):
        outcome = _schedule({"message": "x", "cron_expr": "0 8 * * *", "tz": " Asia/Hong_Kong "})
        assert outcome.ok, outcome.text
        job = cron_service.get_job(outcome.meta["job_id"])
        assert job.schedule.kind == "cron"
        assert job.schedule.tz == "Asia/Hong_Kong"
        assert job.schedule.expr == "0 8 * * *"


class TestInvalidInputRejection:
    def test_no_schedule_kind_rejected(self, cron_service):
        outcome = _schedule({"message": "x"})
        assert outcome.ok is False
        assert "exactly one" in outcome.text

    def test_all_schedule_kinds_rejected(self, cron_service):
        outcome = _schedule(
            {
                "message": "x",
                "at": "2030-01-01T09:00",
                "every_seconds": 60,
                "cron_expr": "0 9 * * *",
            }
        )
        assert outcome.ok is False
        assert "exactly one" in outcome.text

    def test_missing_message_rejected(self, cron_service):
        outcome = _schedule({"every_seconds": 60})
        assert outcome.ok is False
        assert "schedule needs a message" in outcome.text

    def test_whitespace_message_rejected(self, cron_service):
        outcome = _schedule({"message": "   ", "every_seconds": 60})
        assert outcome.ok is False
        assert "schedule needs a message" in outcome.text

    def test_owner_dict_without_kind_rejected(self, cron_service):
        outcome = run_cron_action(
            {
                "action": "list",
                "_cron_owner": {"user_id": "x"},
            }
        )
        assert outcome.ok is False
        assert "not available" in outcome.text

    def test_unknown_action_rejected(self, cron_service):
        outcome = run_cron_action({"action": "frobnicate", "_cron_owner": CHAT_OWNER})
        assert outcome.ok is False
        assert "Unknown action" in outcome.text


class TestRegisterListCancelContract:
    def test_list_without_jobs_reports_empty(self, cron_service):
        outcome = run_cron_action({"action": "list", "_cron_owner": CHAT_OWNER})
        assert outcome.ok is True
        assert outcome.text == "No scheduled tasks for this conversation."
        assert outcome.meta == {}

    def test_list_count_and_schedule_descriptions(self, cron_service):
        assert _schedule({"message": "brief", "cron_expr": "0 8 * * *", "tz": "Asia/Hong_Kong"}).ok
        assert _schedule({"message": "pulse", "every_seconds": 3600, "name": "pulse"}).ok
        outcome = run_cron_action({"action": "list", "_cron_owner": CHAT_OWNER})
        assert outcome.ok is True
        assert outcome.meta["count"] == 2
        assert outcome.text.startswith("2 scheduled task(s):")
        assert "cron `0 8 * * *` (Asia/Hong_Kong)" in outcome.text
        assert "every 3600s" in outcome.text

    def test_cancel_without_job_id_rejected(self, cron_service):
        outcome = run_cron_action({"action": "cancel", "_cron_owner": CHAT_OWNER})
        assert outcome.ok is False
        assert "cancel needs a job_id" in outcome.text

    def test_cancel_unknown_job_id_rejected(self, cron_service):
        outcome = run_cron_action(
            {"action": "cancel", "job_id": "ghost", "_cron_owner": CHAT_OWNER}
        )
        assert outcome.ok is False
        assert "No task `ghost` found" in outcome.text

    def test_created_job_is_listable_then_cancellable(self, cron_service):
        added = _schedule({"message": "water the plants", "every_seconds": 60})
        assert added.ok, added.text
        job_id = added.meta["job_id"]
        assert job_id in run_cron_action({"action": "list", "_cron_owner": CHAT_OWNER}).text
        cancelled = run_cron_action(
            {"action": "cancel", "job_id": job_id, "_cron_owner": CHAT_OWNER}
        )
        assert cancelled.ok, cancelled.text
        assert cron_service.get_job(job_id) is None
        after = run_cron_action({"action": "list", "_cron_owner": CHAT_OWNER})
        assert after.text == "No scheduled tasks for this conversation."

    def test_explicit_delete_after_run_false_overrides_at_default(self, cron_service):
        at = (datetime.now().astimezone() + timedelta(hours=2)).isoformat()
        outcome = _schedule({"message": "x", "at": at, "delete_after_run": False})
        assert outcome.ok, outcome.text
        job = cron_service.get_job(outcome.meta["job_id"])
        assert job.schedule.kind == "at"
        assert job.delete_after_run is False

    def test_name_falls_back_to_message_prefix(self, cron_service):
        outcome = _schedule({"message": "summarize the inbox every morning", "every_seconds": 60})
        assert outcome.ok, outcome.text
        job = cron_service.get_job(outcome.meta["job_id"])
        assert job.name.startswith("summarize the inbox")
