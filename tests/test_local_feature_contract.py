"""Contract for fork-local features on the upstream v1.6.3 baseline."""

from __future__ import annotations

from pathlib import Path

from deeptutor.__version__ import __version__
from deeptutor.api.main import app
from deeptutor.services.config.runtime_settings import (
    DEFAULT_AUTH_SETTINGS,
    RuntimeSettingsService,
)


def test_required_local_and_upstream_route_families_are_installed() -> None:
    paths = set(app.openapi()["paths"])

    assert "/api/auth/handoff" in paths
    assert "/api/auth/handoff/pairing" in paths
    assert "/api/auth/handoff/pairing/{pairing_id}" in paths
    assert "/api/auth/handoff/consume" in paths
    assert any(
        path.startswith("/api/partners/") and path.endswith("/channel-onboarding/start")
        for path in paths
    )
    assert "/api/reading/extensions" in paths
    assert "/api/marginnote4/pair" in paths
    assert "/api/video-learning/renderers" in paths
    assert "/api/video-learning/youtube-session/status" in paths
    assert __version__ == "1.6.3"


def test_retired_kids_product_surface_stays_out_of_the_repository() -> None:
    paths = set(app.openapi()["paths"])
    assert not {
        path
        for path in paths
        if path == "/api/v1/kids"
        or path.startswith("/api/v1/kids/")
        or path == "/api/v1/kids-admin"
        or path.startswith("/api/v1/kids-admin/")
    }

    retired_files = (
        Path("deeptutor/api/routers/kids.py"),
        Path("deeptutor/api/routers/kids_admin.py"),
        Path("deeptutor/kids_rewards.py"),
        Path("deeptutor/multi_user/kids_migration.py"),
        Path("scripts/build_kids_dictionary.py"),
        Path("scripts/kids_dual_track_sync.py"),
        Path("web/lib/kids-api.ts"),
        Path("web/components/kids"),
        Path("web/lib/kids-learning"),
        Path("web/app/kids"),
    )
    assert not [path for path in retired_files if path.exists()]

    web_app = Path("web/app")
    assert not [path for path in web_app.rglob("*") if path.name.lower() == "kids"]
    assert not [path for path in Path("web/tests").rglob("*") if "kids" in path.name.lower()]

    packaged_sources = (
        Path("pyproject.toml").read_text(encoding="utf-8"),
        "\n".join(
            path.read_text(encoding="utf-8", errors="ignore")
            for path in Path("deeptutor").rglob("*.py")
        ),
    )
    assert not any(
        marker in source
        for source in packaged_sources
        for marker in (
            "/api/v1/kids",
            "/api/v1/kids-admin",
            "deeptutor.kids_reward_providers",
            "kids_dual_track_sync",
        )
    )


def test_registration_setting_survives_default_save_and_process_override(
    tmp_path: Path,
) -> None:
    assert DEFAULT_AUTH_SETTINGS["allow_registration"] is False

    service = RuntimeSettingsService(tmp_path / "settings")
    saved = service.save_auth({"allow_registration": True})
    assert saved["allow_registration"] is True

    overridden = RuntimeSettingsService(
        tmp_path / "overridden",
        process_env={"AUTH_ALLOW_REGISTRATION": "true"},
    ).load_auth()
    assert overridden["allow_registration"] is True
