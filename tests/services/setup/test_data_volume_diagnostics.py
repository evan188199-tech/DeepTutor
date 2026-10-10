"""Boundary and message-contract tests for data-volume probes and diagnostics.

Complements ``test_data_volume.py``: focuses on ``parse_id`` /
``resolve_runtime_ids`` edge cases, ``describe_path_ownership`` output, and the
operator-facing ``format_data_volume_permission_error`` message contract.
All filesystem cases use ``tmp_path``; POSIX privilege-drop paths are mocked.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from deeptutor.services.setup.data_volume import (
    DataVolumePermissionError,
    _ensure_writable_as,
    check_container_data_volume,
    current_process_ids,
    describe_path_ownership,
    ensure_data_volume_writable,
    format_data_volume_permission_error,
    parse_id,
    resolve_runtime_ids,
)

# --- parse_id boundaries -----------------------------------------------------


def test_parse_id_strips_whitespace_and_falls_back_to_default() -> None:
    assert parse_id("", default=1000, name="PUID") == 1000
    assert parse_id("   ", default=1000, name="PGID") == 1000
    assert parse_id("\t\n", default=1000, name="PUID") == 1000
    assert parse_id(" 42 ", default=1000, name="PUID") == 42
    assert parse_id("+33", default=1000, name="PUID") == 33


def test_parse_id_error_names_parameter_and_echoes_input() -> None:
    with pytest.raises(ValueError) as excinfo:
        parse_id("alan", default=1000, name="PGID")
    message = str(excinfo.value)
    assert "PGID must be a non-root integer" in message
    assert "'alan'" in message


def test_parse_id_rejects_negative_id() -> None:
    with pytest.raises(ValueError) as excinfo:
        parse_id("-5", default=1000, name="PUID")
    assert "got -5" in str(excinfo.value)


# --- resolve_runtime_ids boundaries ------------------------------------------


def test_resolve_runtime_ids_root_without_env_uses_defaults() -> None:
    assert resolve_runtime_ids(euid=0, egid=0) == (1000, 1000)


def test_resolve_runtime_ids_root_rejects_invalid_puid_with_name() -> None:
    with pytest.raises(ValueError, match="PUID must be a non-root integer"):
        resolve_runtime_ids(puid="abc", euid=0, egid=0)


def test_resolve_runtime_ids_root_rejects_root_puid() -> None:
    with pytest.raises(ValueError, match="non-root"):
        resolve_runtime_ids(puid="0", pgid="100", euid=0, egid=0)


def test_resolve_runtime_ids_root_branch_decided_by_uid_alone() -> None:
    assert resolve_runtime_ids(puid="2000", pgid="2001", euid=0, egid=33) == (2000, 2001)


# --- describe_path_ownership --------------------------------------------------


def test_describe_path_ownership_reports_real_stat_fields(tmp_path: Path) -> None:
    target = tmp_path / "owned"
    target.mkdir()
    target.chmod(0o755)
    info = target.stat()

    description = describe_path_ownership(target)

    assert description == f"uid={info.st_uid} gid={info.st_gid} mode=0755"
    assert description.startswith("uid=")


def test_describe_path_ownership_unreadable_for_missing_path(tmp_path: Path) -> None:
    assert describe_path_ownership(tmp_path / "missing") == "unreadable"


def test_describe_path_ownership_unreadable_when_stat_raises(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    real_stat = Path.stat

    def broken_stat(self: Path, *args: object, **kwargs: object) -> os.stat_result:
        if self == tmp_path:
            raise OSError("injected stat failure")
        return real_stat(self, *args, **kwargs)

    monkeypatch.setattr(Path, "stat", broken_stat)
    assert describe_path_ownership(tmp_path) == "unreadable"


# --- format_data_volume_permission_error message contract ---------------------


def test_error_message_carries_fixed_operator_guidance(tmp_path: Path) -> None:
    target = tmp_path / "knowledge_bases"
    target.mkdir()
    message = format_data_volume_permission_error(target, uid=1000, gid=1001)

    assert "Data directory is not writable by the running process" in message
    assert "euid=1000" in message
    assert "egid=1001" in message
    assert "is uid=" in message
    assert "set PUID and PGID" in message
    assert "instead of chowning the mount" in message
    assert "non-root" in message


def test_error_message_appends_cause_only_when_provided(tmp_path: Path) -> None:
    target = tmp_path / "knowledge_bases"
    target.mkdir()
    with_cause = format_data_volume_permission_error(
        target, uid=1000, gid=1000, cause=RuntimeError("disk boom")
    )
    without_cause = format_data_volume_permission_error(target, uid=1000, gid=1000)

    assert "disk boom" in with_cause
    assert "disk boom" not in without_cause
    assert not without_cause.endswith(") ")


def test_error_message_defaults_ids_to_current_process(tmp_path: Path) -> None:
    uid, gid = current_process_ids()
    message = format_data_volume_permission_error(tmp_path / "kb")

    assert f"euid={uid}" in message
    assert f"egid={gid}" in message


# --- ensure_data_volume_writable privilege-drop boundaries (mocked os API) ----


def _mock_root_process(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(os, "geteuid", lambda: 0, raising=False)
    monkeypatch.setattr(os, "getegid", lambda: 0, raising=False)
    monkeypatch.setattr(os, "fork", lambda: 1234, raising=False)
    monkeypatch.setattr(os, "setuid", lambda _uid: None, raising=False)
    monkeypatch.setattr(os, "setgid", lambda _gid: None, raising=False)


def test_root_probe_parent_raises_on_nonzero_child_exit(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _mock_root_process(monkeypatch)
    target = tmp_path / "mounted" / "knowledge_bases"
    failed_status = 1 << 8  # WIFEXITED true, WEXITSTATUS == 1
    monkeypatch.setattr(os, "waitpid", lambda pid, _flags: (pid, failed_status))

    with pytest.raises(DataVolumePermissionError, match="not writable") as excinfo:
        ensure_data_volume_writable(target, uid=1001, gid=1002)

    assert "euid=1001" in str(excinfo.value)
    assert not target.exists()


def test_root_probe_parent_succeeds_when_child_exits_zero(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _mock_root_process(monkeypatch)
    target = tmp_path / "mounted" / "knowledge_bases"
    waited: list[tuple[int, int]] = []
    monkeypatch.setattr(
        os, "waitpid", lambda pid, flags: waited.append((pid, flags)) or (pid, 0)
    )

    ensure_data_volume_writable(target, uid=1001, gid=1002)

    assert waited == [(1234, 0)]
    assert not target.exists()
    assert not list(tmp_path.rglob(".deeptutor-write-probe-*"))


def test_root_probe_without_fork_api_probes_in_process(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(os, "geteuid", lambda: 0, raising=False)
    monkeypatch.setattr(os, "getegid", lambda: 0, raising=False)
    monkeypatch.delattr(os, "fork", raising=False)

    target = tmp_path / "data" / "knowledge_bases"
    ensure_data_volume_writable(target, uid=1234, gid=1234)

    assert target.is_dir()
    assert not any(target.glob(".deeptutor-write-probe-*"))


def test_ensure_writable_as_requires_full_posix_drop_apis(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delattr(os, "fork", raising=False)

    with pytest.raises(RuntimeError, match="privilege-drop APIs are unavailable"):
        _ensure_writable_as(tmp_path / "kb", 1000, 1000)


# --- check_container_data_volume environment contract --------------------------


def test_container_check_falls_back_to_deeptutor_prefix_env(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(os, "geteuid", lambda: 0, raising=False)
    monkeypatch.setattr(os, "getegid", lambda: 0, raising=False)
    monkeypatch.delenv("PUID", raising=False)
    monkeypatch.delenv("PGID", raising=False)
    monkeypatch.setenv("DEEPTUTOR_PUID", "abc")
    data_root = tmp_path / "app-data"

    with pytest.raises(ValueError) as excinfo:
        check_container_data_volume(data_root)

    assert "PUID must be a non-root integer" in str(excinfo.value)
    assert "'abc'" in str(excinfo.value)
    assert not data_root.exists()


def test_container_check_prefers_puid_over_deeptutor_prefix(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(os, "geteuid", lambda: 0, raising=False)
    monkeypatch.setattr(os, "getegid", lambda: 0, raising=False)
    monkeypatch.setenv("PUID", "oops")
    monkeypatch.setenv("DEEPTUTOR_PUID", "1000")
    monkeypatch.delenv("PGID", raising=False)
    data_root = tmp_path / "app-data"

    with pytest.raises(ValueError) as excinfo:
        check_container_data_volume(data_root)

    assert "'oops'" in str(excinfo.value)
