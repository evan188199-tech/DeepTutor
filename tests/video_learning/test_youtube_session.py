import json
from pathlib import Path
import stat

import pytest

from deeptutor.video_learning.subtitle_prefetch import transcript_fetch
from deeptutor.video_learning.youtube_session import (
    HostChromeSessionStore,
    YouTubeCookieStore,
    YouTubeLoginManager,
    _is_allowed_domain,
)


def test_youtube_cookie_store_filters_domains_and_protects_files(tmp_path: Path, monkeypatch):
    monkeypatch.setattr("deeptutor.multi_user.paths.SYSTEM_ROOT", tmp_path / "system")
    cookies = [
        {"name": "SID", "value": "private", "domain": ".youtube.com", "path": "/", "secure": True},
        {"name": "SAPISID", "value": "private", "domain": ".google.com", "path": "/", "secure": True},
        {"name": "foreign", "value": "never-store", "domain": ".example.com", "path": "/"},
    ]
    assert YouTubeCookieStore.save("evan", cookies)
    payload = YouTubeCookieStore.read("evan")
    assert payload is not None
    assert {cookie["domain"] for cookie in payload["cookies"]} == {".youtube.com", ".google.com"}
    path = YouTubeCookieStore._path("evan")
    assert stat.S_IMODE(path.stat().st_mode) == 0o600
    assert stat.S_IMODE(path.parent.stat().st_mode) == 0o700

    cookiefile = YouTubeCookieStore.write_cookiefile("evan", tmp_path)
    assert cookiefile is not None
    assert "example.com" not in cookiefile.read_text(encoding="utf-8")
    assert stat.S_IMODE(cookiefile.stat().st_mode) == 0o600
    assert YouTubeCookieStore.read("another-owner") is None


def test_youtube_domain_filter_is_exact_or_subdomain():
    assert _is_allowed_domain("accounts.google.com")
    assert _is_allowed_domain("www.youtube.com")
    assert not _is_allowed_domain("notyoutube.com")
    assert not _is_allowed_domain("youtube.com.example.org")


def test_legacy_transcript_fetch_defaults_to_not_requested():
    material = {"transcript": {"language": "en", "source": "old", "cues": []}}
    assert transcript_fetch(material)["status"] == "not_requested"


def test_host_chrome_opt_in_keeps_only_consent_metadata(tmp_path: Path, monkeypatch):
    monkeypatch.setattr("deeptutor.multi_user.paths.SYSTEM_ROOT", tmp_path / "system")

    HostChromeSessionStore.enable("evan")

    path = HostChromeSessionStore._path("evan")
    assert HostChromeSessionStore.enabled("evan")
    assert set(json.loads(path.read_text(encoding="utf-8"))) == {"enabled", "enabled_at"}
    assert stat.S_IMODE(path.stat().st_mode) == 0o600
    assert stat.S_IMODE(path.parent.stat().st_mode) == 0o700

    HostChromeSessionStore.delete("evan")
    assert not path.exists()


@pytest.mark.asyncio
async def test_host_chrome_opt_in_is_reported_as_connected(tmp_path: Path, monkeypatch):
    monkeypatch.setattr("deeptutor.multi_user.paths.SYSTEM_ROOT", tmp_path / "system")
    monkeypatch.setattr("deeptutor.video_learning.youtube_session.find_chrome", lambda: "/Applications/Google Chrome.app")
    HostChromeSessionStore.enable("evan")

    status = await YouTubeLoginManager().status("evan")

    assert status["connection"] == "connected"
    assert status["helper_available"] is True
    assert status["last_validated_at"]
    assert status["last_error_code"] is None
