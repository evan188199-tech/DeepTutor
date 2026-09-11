"""Contract for fork-local features on the upstream v1.6.7 baseline."""

from __future__ import annotations

from pathlib import Path

from deeptutor.__version__ import __version__
from deeptutor.api.main import app
from deeptutor.services.config.runtime_settings import (
    DEFAULT_AUTH_SETTINGS,
    RuntimeSettingsService,
)

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]


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
    assert __version__ == "1.6.7"


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
        REPOSITORY_ROOT / "deeptutor/api/routers/kids.py",
        REPOSITORY_ROOT / "deeptutor/api/routers/kids_admin.py",
        REPOSITORY_ROOT / "deeptutor/kids_rewards.py",
        REPOSITORY_ROOT / "deeptutor/multi_user/kids_migration.py",
        REPOSITORY_ROOT / "scripts/build_kids_dictionary.py",
        REPOSITORY_ROOT / "scripts/kids_dual_track_sync.py",
        REPOSITORY_ROOT / "web/lib/kids-api.ts",
        REPOSITORY_ROOT / "web/components/kids",
        REPOSITORY_ROOT / "web/lib/kids-learning",
        REPOSITORY_ROOT / "web/app/kids",
    )
    assert not [path for path in retired_files if path.exists()]

    web_app = REPOSITORY_ROOT / "web/app"
    assert not [path for path in web_app.rglob("*") if path.name.lower() == "kids"]
    assert not [
        path for path in (REPOSITORY_ROOT / "web/tests").rglob("*") if "kids" in path.name.lower()
    ]

    packaged_sources = (
        (REPOSITORY_ROOT / "pyproject.toml").read_text(encoding="utf-8"),
        "\n".join(
            path.read_text(encoding="utf-8", errors="ignore")
            for path in (REPOSITORY_ROOT / "deeptutor").rglob("*.py")
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
