"""Cron pure logic: schedule parsing, next-trigger math, due pickup/dedup,
failure visibility. No scheduler loop is started anywhere in this module."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
import time
from zoneinfo import ZoneInfo

import pytest

from deeptutor.services.cron import repository as cron_repository
from deeptutor.services.cron.executor import _notification_text, _reminder_prompt
from deeptutor.services.cron.service import (
    _MAX_RUN_HISTORY,
    CronJob,
    CronOwner,
    CronRunRecord,
    CronSchedule,
    CronService,
    compute_next_run,
    validate_schedule,
)


def _now_ms() -> int:
    return int(time.time() * 1000)


def _chat_owner(user_id: str = "local-admin") -> CronOwner:
    return CronOwner(kind="chat", user_id=user_id, session_id="s1")


def _job_payload(job_id: str, next_run_ms: int | None) -> dict:
    return {
        "id": job_id,
        "name": job_id,
        "message": "ping",
        "schedule": {"kind": "every", "every_seconds": 3600},
        "owner": {"kind": "chat", "user_id": "local-admin", "session_id": "s1"},
        "enabled": True,
        "delete_after_run": False,
        "created_at_ms": _now_ms(),
        "state": {"next_run_at_ms": next_run_ms, "run_history": []},
    }


class TestScheduleParsing:
    def test_from_dict_round_trip_preserves_typed_state(self):
        record = {"run_at_ms": 1234, "status": "error", "duration_ms": 5, "error": "boom"}
        raw = _job_payload("job-1", 999)
        raw["state"]["last_run_at_ms"] = 1234
        raw["state"]["last_status"] = "error"
        raw["state"]["last_error"] = "boom"
        raw["state"]["run_history"] = [record]

        job = CronJob.from_dict(raw)

        assert job.id == "job-1"
        assert job.schedule == CronSchedule(kind="every", every_seconds=3600)
        assert job.owner.key == "chat:local-admin"
        assert job.state.last_status == "error"
        assert job.state.run_history == [CronRunRecord(**record)]
        assert isinstance(job.state.run_history[0], CronRunRecord)

    def test_from_dict_fills_defaults_for_missing_fields(self):
        job = CronJob.from_dict({"id": "job-2"})
        assert job.name == ""
        assert job.schedule == CronSchedule(kind="every")
        assert job.owner == CronOwner(kind="chat")
        assert job.enabled is True
        assert job.delete_after_run is False
        assert job.created_at_ms == 0
        assert job.state.next_run_at_ms is None
        assert job.state.run_history == []

    def test_owner_key_shapes(self):
        assert CronOwner(kind="chat", user_id="alice").key == "chat:alice"
        # A chat owner without a user id falls back to the local admin scope.
        assert CronOwner(kind="chat").key == "chat:local-admin"
        assert CronOwner(kind="partner", partner_id="ada").key == "partner:ada"


class TestComputeNextRun:
    def test_unknown_or_degenerate_schedules_never_fire(self):
        now = _now_ms()
        assert compute_next_run(CronSchedule(kind="wat"), now) is None
        assert compute_next_run(CronSchedule(kind="cron"), now) is None
        assert compute_next_run(CronSchedule(kind="every", every_seconds=-5), now) is None
        assert compute_next_run(CronSchedule(kind="at", at_ms=None), now) is None

    def test_cron_expression_resolves_in_the_given_timezone(self):
        pytest.importorskip("croniter")
        now_ms = int(
            datetime(2026, 1, 15, 12, 0, tzinfo=timezone.utc).timestamp() * 1000
        )  # 20:00 in Shanghai, 07:00 in New York

        shanghai = compute_next_run(
            CronSchedule(kind="cron", expr="0 9 * * *", tz="Asia/Shanghai"), now_ms
        )
        utc = compute_next_run(CronSchedule(kind="cron", expr="0 9 * * *", tz="UTC"), now_ms)
        ny = compute_next_run(
            CronSchedule(kind="cron", expr="0 9 * * *", tz="America/New_York"), now_ms
        )

        assert shanghai is not None and utc is not None and ny is not None
        # Each trigger is that zone's next 09:00 local wall clock.
        for next_ms, tz_name in (
            (shanghai, "Asia/Shanghai"),
            (utc, "UTC"),
            (ny, "America/New_York"),
        ):
            local = datetime.fromtimestamp(next_ms / 1000, tz=ZoneInfo(tz_name))
            assert (local.hour, local.minute) == (9, 0)
            assert local > datetime.fromtimestamp(now_ms / 1000, tz=ZoneInfo(tz_name))
        # The same wall clock in zones 8h apart lands exactly 8h apart in epoch time.
        assert utc - shanghai == 8 * 3600 * 1000

    def test_cron_expression_tracks_dst_offset_change(self):
        pytest.importorskip("croniter")
        # 2026-03-07 20:00 UTC is 15:00 EST (UTC-5); the next 09:00 local is
        # on the spring-forward day, which is already EDT (UTC-4).
        now_ms = int(datetime(2026, 3, 7, 20, 0, tzinfo=timezone.utc).timestamp() * 1000)

        next_ms = compute_next_run(
            CronSchedule(kind="cron", expr="0 9 * * *", tz="America/New_York"), now_ms
        )

        assert next_ms is not None
        local = datetime.fromtimestamp(next_ms / 1000, tz=ZoneInfo("America/New_York"))
        assert (local.hour, local.minute) == (9, 0)
        assert local.utcoffset() == timedelta(hours=-4)


class TestValidateSchedule:
    def test_accepts_each_valid_kind(self):
        validate_schedule(CronSchedule(kind="at", at_ms=_now_ms() + 60_000))
        validate_schedule(CronSchedule(kind="every", every_seconds=30))
        pytest.importorskip("croniter")
        validate_schedule(CronSchedule(kind="cron", expr="*/5 * * * *", tz="UTC"))

    def test_rejects_unknown_kind(self):
        with pytest.raises(ValueError, match="unknown schedule kind"):
            validate_schedule(CronSchedule(kind="hourly-ish"))

    def test_rejects_cron_expressions_that_can_never_run(self):
        pytest.importorskip("croniter")
        # February 31st does not exist, so the expression can never trigger.
        with pytest.raises(ValueError, match="invalid cron expression"):
            validate_schedule(CronSchedule(kind="cron", expr="0 0 31 2 *", tz="UTC"))
        # An empty expression yields no next trigger at all.
        with pytest.raises(ValueError, match="never fires"):
            validate_schedule(CronSchedule(kind="cron", expr="", tz="UTC"))


class TestDuePickup:
    @pytest.mark.asyncio
    async def test_tick_fires_only_due_jobs(self, tmp_path):
        fired: list[str] = []

        async def on_job(job):
            fired.append(job.id)
            return "ok", None

        service = CronService(store_path=tmp_path / "jobs.sqlite3", on_job=on_job)
        due = service.add_job(
            name="due",
            message="x",
            schedule=CronSchedule(kind="every", every_seconds=3600),
            owner=_chat_owner(),
        )
        future = service.add_job(
            name="future",
            message="y",
            schedule=CronSchedule(kind="every", every_seconds=3600),
            owner=_chat_owner(),
        )
        due.state.next_run_at_ms = _now_ms() - 10
        future.state.next_run_at_ms = _now_ms() + 3_600_000

        await service._tick()

        assert fired == [due.id]
        assert future.state.last_run_at_ms is None

    @pytest.mark.asyncio
    async def test_disabled_job_is_never_picked_up(self, tmp_path):
        fired: list[str] = []

        async def on_job(job):
            fired.append(job.id)
            return "ok", None

        service = CronService(store_path=tmp_path / "jobs.sqlite3", on_job=on_job)
        job = service.add_job(
            name="off",
            message="x",
            schedule=CronSchedule(kind="every", every_seconds=3600),
            owner=_chat_owner(),
        )
        job.enabled = False
        job.state.next_run_at_ms = _now_ms() - 10

        await service._tick()

        assert fired == []
        assert job.state.last_status is None

    @pytest.mark.asyncio
    async def test_overdue_job_fires_once_per_tick(self, tmp_path):
        """A job left overdue for hours must not replay once per interval."""
        fired: list[str] = []

        async def on_job(job):
            fired.append(job.id)
            return "ok", None

        service = CronService(store_path=tmp_path / "jobs.sqlite3", on_job=on_job)
        job = service.add_job(
            name="backlog",
            message="x",
            schedule=CronSchedule(kind="every", every_seconds=60),
            owner=_chat_owner(),
        )
        job.state.next_run_at_ms = _now_ms() - 6 * 3600_000

        await service._tick()

        assert fired == [job.id]
        assert service.get_job(job.id) is not None
        assert service.get_job(job.id).state.next_run_at_ms > _now_ms()

    @pytest.mark.asyncio
    async def test_two_jobs_due_at_the_same_instant_each_fire_once(self, tmp_path):
        fired: list[str] = []

        async def on_job(job):
            fired.append(job.id)
            return "ok", None

        service = CronService(store_path=tmp_path / "jobs.sqlite3", on_job=on_job)
        due_ms = _now_ms() - 10
        first = service.add_job(
            name="a",
            message="x",
            schedule=CronSchedule(kind="every", every_seconds=3600),
            owner=_chat_owner("alice"),
        )
        second = service.add_job(
            name="b",
            message="y",
            schedule=CronSchedule(kind="every", every_seconds=3600),
            owner=_chat_owner("bob"),
        )
        first.state.next_run_at_ms = due_ms
        second.state.next_run_at_ms = due_ms

        await service._tick()

        assert sorted(fired) == sorted([first.id, second.id])

    @pytest.mark.asyncio
    async def test_job_without_next_run_is_skipped(self, tmp_path):
        fired: list[str] = []

        async def on_job(job):
            fired.append(job.id)
            return "ok", None

        service = CronService(store_path=tmp_path / "jobs.sqlite3", on_job=on_job)
        service.add_job(
            name="unarmed",
            message="x",
            schedule=CronSchedule(kind="cron", expr="0 9 * * *", tz="UTC"),
            owner=_chat_owner(),
        )
        service.get_job(list(service._jobs)[0]).state.next_run_at_ms = None

        await service._tick()

        assert fired == []


class TestFailureVisibility:
    @pytest.mark.asyncio
    async def test_error_status_is_visible_and_job_survives(self, tmp_path):
        async def on_job(job):
            return "error", "provider unreachable"

        service = CronService(store_path=tmp_path / "jobs.sqlite3", on_job=on_job)
        job = service.add_job(
            name="flaky",
            message="x",
            schedule=CronSchedule(kind="every", every_seconds=3600),
            owner=_chat_owner(),
        )
        job.state.next_run_at_ms = _now_ms() - 10

        await service._tick()

        refreshed = service.get_job(job.id)
        assert refreshed is not None
        assert refreshed.state.last_status == "error"
        assert refreshed.state.last_error == "provider unreachable"
        assert refreshed.state.run_history[-1].status == "error"
        assert refreshed.state.run_history[-1].error == "provider unreachable"
        assert refreshed.state.next_run_at_ms is not None

    @pytest.mark.asyncio
    async def test_skipped_status_is_recorded(self, tmp_path):
        async def on_job(job):
            return "skipped", "partner not running"

        service = CronService(store_path=tmp_path / "jobs.sqlite3", on_job=on_job)
        job = service.add_job(
            name="guard",
            message="x",
            schedule=CronSchedule(kind="every", every_seconds=3600),
            owner=_chat_owner(),
        )
        job.state.next_run_at_ms = _now_ms() - 10

        await service._tick()

        refreshed = service.get_job(job.id)
        assert refreshed.state.last_status == "skipped"
        assert refreshed.state.last_error == "partner not running"

    @pytest.mark.asyncio
    async def test_missing_callback_defaults_to_skipped(self, tmp_path):
        service = CronService(store_path=tmp_path / "jobs.sqlite3", on_job=None)
        job = service.add_job(
            name="no-runner",
            message="x",
            schedule=CronSchedule(kind="every", every_seconds=3600),
            owner=_chat_owner(),
        )
        job.state.next_run_at_ms = _now_ms() - 10

        await service._tick()

        refreshed = service.get_job(job.id)
        assert refreshed.state.last_status == "skipped"
        assert refreshed.state.last_error is None

    @pytest.mark.asyncio
    async def test_run_history_is_capped(self, tmp_path):
        async def on_job(job):
            return "ok", None

        service = CronService(store_path=tmp_path / "jobs.sqlite3", on_job=on_job)
        job = service.add_job(
            name="chatty",
            message="x",
            schedule=CronSchedule(kind="every", every_seconds=3600),
            owner=_chat_owner(),
        )

        for _ in range(_MAX_RUN_HISTORY + 3):
            await service._run_job(job)

        refreshed = service.get_job(job.id)
        assert len(refreshed.state.run_history) == _MAX_RUN_HISTORY
        assert all(record.status == "ok" for record in refreshed.state.run_history)

    @pytest.mark.asyncio
    async def test_one_shot_job_is_removed_even_after_failure(self, tmp_path):
        async def on_job(job):
            return "error", "boom"

        service = CronService(store_path=tmp_path / "jobs.sqlite3", on_job=on_job)
        job = service.add_job(
            name="once-fails",
            message="x",
            schedule=CronSchedule(kind="at", at_ms=_now_ms() + 60_000),
            owner=_chat_owner(),
        )
        job.state.next_run_at_ms = _now_ms() - 10

        await service._tick()

        assert service.get_job(job.id) is None
        assert service.list_jobs() == []


class TestRepositoryPickupOrdering:
    def test_list_payloads_orders_by_next_run_then_id(self, tmp_path):
        repo = cron_repository.SQLiteCronRepository(tmp_path / "jobs.sqlite3")
        repo.upsert(_job_payload("job-c", 3000))
        repo.upsert(_job_payload("job-a", 1000))
        repo.upsert(_job_payload("job-b", 1000))
        repo.upsert(_job_payload("job-z", None))

        # COALESCE(next_run_at_ms, 0) puts jobs without a next trigger first.
        assert [payload["id"] for payload in repo.list_payloads()] == [
            "job-z",
            "job-a",
            "job-b",
            "job-c",
        ]

    def test_owner_scoped_delete_and_revision_accounting(self, tmp_path):
        repo = cron_repository.SQLiteCronRepository(tmp_path / "jobs.sqlite3")
        payload = _job_payload("job-1", 5000)
        repo.upsert(payload)
        revision = repo.revision()

        assert repo.delete("job-1", owner_key="partner:ada") is False
        assert repo.revision() == revision
        assert repo.delete("job-1", owner_key="chat:local-admin") is True
        assert repo.revision() == revision + 1
        assert repo.list_payloads() == []

    def test_owner_key_derivation(self):
        derive = cron_repository.SQLiteCronRepository._owner_key
        assert derive({"owner": {"kind": "partner", "partner_id": "ada"}}) == "partner:ada"
        assert derive({"owner": {"kind": "partner"}}) == "partner:"
        assert derive({"owner": {"kind": "chat", "user_id": "alice"}}) == "chat:alice"
        assert derive({"owner": {"kind": "chat"}}) == "chat:local-admin"
        assert derive({}) == "chat:local-admin"


class TestExecutorHelpers:
    def test_reminder_prompt_embeds_job_message(self):
        job = CronJob.from_dict(_job_payload("job-1", None))
        prompt = _reminder_prompt(job)
        assert job.message in prompt
        assert job.id not in prompt

    def test_notification_text_compacts_and_truncates(self):
        assert _notification_text("  hello   world \n") == "hello world"
        long = "x" * 300
        trimmed = _notification_text(long)
        assert len(trimmed) == 240
        assert trimmed.endswith("…")
        assert _notification_text("") == ""
