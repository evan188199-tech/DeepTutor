import json
from pathlib import Path
import stat

from deeptutor.multi_user import paths
from deeptutor.video_learning.youtube_session import HostChromeSessionStore


def test_host_chrome_consent_is_private_and_contains_no_cookies(
    tmp_path: Path, monkeypatch
) -> None:
    monkeypatch.setattr(paths, "SYSTEM_ROOT", tmp_path / "system")

    HostChromeSessionStore.enable("evan")

    path = HostChromeSessionStore._path("evan")
    assert set(json.loads(path.read_text(encoding="utf-8"))) == {
        "enabled",
        "enabled_at",
    }
    assert stat.S_IMODE(path.parent.stat().st_mode) == 0o700
    assert stat.S_IMODE(path.stat().st_mode) == 0o600
    assert HostChromeSessionStore.enabled("evan")
    HostChromeSessionStore.delete("evan")
    assert not HostChromeSessionStore.enabled("evan")
