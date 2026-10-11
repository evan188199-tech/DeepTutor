"""The web continuity state file must stay owner-only and atomically replaced."""

from __future__ import annotations

import json
import os
import stat

import pytest

from deeptutor.partners.config.paths import get_partner_user_dir
from deeptutor.services.partners.web_continuity import set_web_continuity

posix_only = pytest.mark.skipif(
    os.name != "posix", reason="POSIX permission bits are not modelled on Windows"
)


def _state_path():
    return get_partner_user_dir("ada", "account-a") / "web_continuity.json"


@posix_only
def test_state_file_is_owner_only(partners_root):
    set_web_continuity("ada", "account-a", enabled=True, session_key="web-current")
    assert stat.S_IMODE(_state_path().stat().st_mode) == 0o600


@posix_only
def test_state_file_stays_owner_only_under_permissive_umask(partners_root):
    previous = os.umask(0)
    try:
        set_web_continuity("ada", "account-a", enabled=True, session_key="web-current")
    finally:
        os.umask(previous)
    assert stat.S_IMODE(_state_path().stat().st_mode) == 0o600


@posix_only
def test_replacement_tightens_a_preexisting_wide_file(partners_root):
    set_web_continuity("ada", "account-a", enabled=True, session_key="web-one")
    path = _state_path()
    path.chmod(0o666)

    set_web_continuity("ada", "account-a", enabled=True, session_key="web-two")

    assert stat.S_IMODE(path.stat().st_mode) == 0o600
    assert json.loads(path.read_text(encoding="utf-8"))["session_key"] == "web-two"


def test_failed_write_keeps_previous_state_and_leaves_no_litter(partners_root, monkeypatch):
    import deeptutor.services.file_io as file_io

    set_web_continuity("ada", "account-a", enabled=True, session_key="web-one")
    path = _state_path()

    def exploding_dump(*_args, **_kwargs):
        raise OSError("disk full")

    monkeypatch.setattr(file_io.json, "dump", exploding_dump)

    with pytest.raises(OSError):
        set_web_continuity("ada", "account-a", enabled=True, session_key="web-two")

    assert json.loads(path.read_text(encoding="utf-8"))["session_key"] == "web-one"
    leftovers = sorted(
        entry.name for entry in path.parent.iterdir() if not entry.name.startswith(".")
    )
    assert leftovers == [path.name]
