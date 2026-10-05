from datetime import datetime, timedelta, timezone

from deeptutor.api.utils.task_id_manager import TaskIDManager


def _manager() -> TaskIDManager:
    manager = TaskIDManager()
    manager._task_ids = {}
    manager._task_metadata = {}
    return manager


def test_generate_prunes_expired_completed_tasks() -> None:
    manager = _manager()
    old_id = manager.generate_task_id("kb", "old")
    manager.update_task_status(old_id, "completed")
    manager._task_metadata[old_id]["finished_at"] = (
        datetime.now() - timedelta(hours=25)
    ).isoformat()

    manager.generate_task_id("kb", "new")

    assert old_id not in manager._task_metadata
    assert "old" not in manager._task_ids


def test_completed_task_metadata_has_hard_count_bound() -> None:
    manager = _manager()
    manager._MAX_COMPLETED_TASKS = 3

    for index in range(8):
        task_id = manager.generate_task_id("kb", f"task-{index}")
        manager.update_task_status(task_id, "completed")

    manager.cleanup_old_tasks()

    assert len(manager._task_metadata) == 3
    assert len(manager._task_ids) == 3


def test_cleanup_removes_aware_utc_finished_tasks() -> None:
    manager = _manager()
    old_id = manager.generate_task_id("kb", "old")
    manager.update_task_status(old_id, "completed")
    manager._task_metadata[old_id]["finished_at"] = (
        datetime.now(timezone.utc) - timedelta(hours=25)
    ).isoformat()

    manager.cleanup_old_tasks()

    assert old_id not in manager._task_metadata
    assert "old" not in manager._task_ids


def test_cleanup_keeps_recent_aware_task_and_skips_unparseable_finished_at() -> None:
    manager = _manager()
    recent_id = manager.generate_task_id("kb", "recent")
    manager.update_task_status(recent_id, "completed")
    manager._task_metadata[recent_id]["finished_at"] = datetime.now(timezone.utc).isoformat()

    broken_id = manager.generate_task_id("kb", "broken")
    manager.update_task_status(broken_id, "completed")
    manager._task_metadata[broken_id]["finished_at"] = "not-a-timestamp"

    manager.cleanup_old_tasks()

    assert recent_id in manager._task_metadata
    assert broken_id in manager._task_metadata


def test_finished_at_is_stored_as_aware_utc() -> None:
    manager = _manager()
    task_id = manager.generate_task_id("kb", "task")
    manager.update_task_status(task_id, "completed")

    finished_at = datetime.fromisoformat(manager._task_metadata[task_id]["finished_at"])
    assert finished_at.tzinfo is not None
    assert finished_at.utcoffset() == timedelta(0)
