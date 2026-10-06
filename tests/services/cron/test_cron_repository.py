"""SQLiteCronRepository migration lock: cross-platform branches and mutual exclusion."""

from __future__ import annotations

import sys
import threading
from types import SimpleNamespace

import pytest

from deeptutor.services.cron import repository


class TestMigrationLock:
    def test_acquire_release_round_trip(self, tmp_path):
        repo = repository.SQLiteCronRepository(tmp_path / "cron.db")
        with repo._migration_lock():
            assert repo._migration_lock_path.exists()

    def test_mutually_excludes_concurrent_holders(self, tmp_path):
        repo = repository.SQLiteCronRepository(tmp_path / "cron.db")
        holder_entered = threading.Event()
        release_holder = threading.Event()
        second_entered = threading.Event()
        acquired_order: list[str] = []

        def holder():
            with repo._migration_lock():
                acquired_order.append("holder")
                holder_entered.set()
                release_holder.wait(5)

        holder_thread = threading.Thread(target=holder)
        holder_thread.start()
        assert holder_entered.wait(2)

        def second():
            with repo._migration_lock():
                acquired_order.append("second")
                second_entered.set()

        second_thread = threading.Thread(target=second)
        second_thread.start()

        # While the holder keeps the lock, the second acquirer is locked out;
        # it can only enter after the holder releases. Recording the
        # acquisition order proves the blocking actually happened without
        # relying on wall-clock durations.
        assert not second_entered.wait(0.2)
        release_holder.set()
        assert second_entered.wait(5)

        holder_thread.join(timeout=5)
        second_thread.join(timeout=5)
        assert not holder_thread.is_alive()
        assert not second_thread.is_alive()
        assert acquired_order == ["holder", "second"]

    def test_acquire_while_held_fails(self, tmp_path):
        fcntl = pytest.importorskip("fcntl")
        repo = repository.SQLiteCronRepository(tmp_path / "cron.db")
        with repo._migration_lock():
            with repo._migration_lock_path.open("a+b") as probe:
                with pytest.raises(OSError):
                    fcntl.flock(probe.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)

    def test_module_does_not_bind_fcntl_at_import(self):
        # Top-level ``import fcntl`` breaks cron startup on Windows (#1183).
        assert "fcntl" not in repository.__dict__

    def test_uses_msvcrt_locking_on_windows(self, tmp_path, monkeypatch: pytest.MonkeyPatch):
        repo = repository.SQLiteCronRepository(tmp_path / "cron.db")
        calls: list[tuple[int, int]] = []
        fake_msvcrt = SimpleNamespace(
            LK_LOCK=1,
            LK_UNLCK=2,
            locking=lambda _fileno, mode, length: calls.append((mode, length)),
        )
        monkeypatch.setattr(repository, "sys", SimpleNamespace(platform="win32"))
        monkeypatch.setitem(sys.modules, "msvcrt", fake_msvcrt)

        with repo._migration_lock():
            assert calls == [(fake_msvcrt.LK_LOCK, 1)]

        assert calls == [
            (fake_msvcrt.LK_LOCK, 1),
            (fake_msvcrt.LK_UNLCK, 1),
        ]

    def test_uses_fcntl_locking_on_posix(self, tmp_path, monkeypatch: pytest.MonkeyPatch):
        repo = repository.SQLiteCronRepository(tmp_path / "cron.db")
        calls: list[int] = []
        fake_fcntl = SimpleNamespace(
            LOCK_EX=1,
            LOCK_UN=2,
            flock=lambda _fileno, mode: calls.append(mode),
        )
        monkeypatch.setattr(repository, "sys", SimpleNamespace(platform="linux"))
        monkeypatch.setitem(sys.modules, "fcntl", fake_fcntl)

        with repo._migration_lock():
            assert calls == [fake_fcntl.LOCK_EX]

        assert calls == [
            fake_fcntl.LOCK_EX,
            fake_fcntl.LOCK_UN,
        ]
