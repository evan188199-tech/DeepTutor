"""LTI platform registrations in RuntimeSettingsService (lti.json)."""

from __future__ import annotations

from pathlib import Path

from deeptutor.services.config.runtime_settings import RuntimeSettingsService

_VALID_PLATFORM = {
    "issuer": "https://lms.example.edu/",
    "client_id": "deeptutor-client-1",
    "deployment_ids": ["deployment-7", ""],
    "auth_login_url": "https://lms.example.edu/mod/lti/auth.php",
    "target_link_uri": "https://deeptutor.example.edu/app",
    "key_set_url": "https://lms.example.edu/mod/lti/certs.php",
}


def test_lti_defaults_are_disabled(tmp_path: Path) -> None:
    svc = RuntimeSettingsService(tmp_path, process_env={})
    loaded = svc.load_lti(include_process_overrides=False)
    assert loaded == {"version": 1, "enabled": False, "platforms": []}
    assert (tmp_path / "lti.json").exists()


def test_lti_settings_roundtrip_normalizes_platform(tmp_path: Path) -> None:
    svc = RuntimeSettingsService(tmp_path, process_env={})
    svc.save_lti({"enabled": True, "platforms": [_VALID_PLATFORM]})

    loaded = svc.load_lti(include_process_overrides=False)
    assert loaded["enabled"] is True
    (platform,) = loaded["platforms"]
    assert platform["issuer"] == "https://lms.example.edu"
    assert platform["deployment_ids"] == ["deployment-7"]
    assert platform["key_set"] is None


def test_lti_settings_drop_invalid_platforms(tmp_path: Path) -> None:
    svc = RuntimeSettingsService(tmp_path, process_env={})
    invalid = [
        {"issuer": "not-a-url", "client_id": "x"},
        {**_VALID_PLATFORM, "deployment_ids": []},
        {**_VALID_PLATFORM, "key_set_url": ""},
        {**_VALID_PLATFORM, "target_link_uri": "javascript:alert(1)"},
        "not-even-a-dict",
    ]
    svc.save_lti({"enabled": True, "platforms": invalid})

    loaded = svc.load_lti(include_process_overrides=False)
    assert loaded["platforms"] == []
    assert loaded["enabled"] is True


def test_lti_enabled_env_override(tmp_path: Path) -> None:
    svc = RuntimeSettingsService(
        tmp_path,
        process_env={"LTI_ENABLED": "true"},
    )
    svc.save_lti({"platforms": [_VALID_PLATFORM]})

    loaded = svc.load_lti(include_process_overrides=True)
    assert loaded["enabled"] is True
