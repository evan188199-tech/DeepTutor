"""Contract for fork-local features on the upstream v1.6.12 baseline."""

from __future__ import annotations

from pathlib import Path

from deeptutor.api.main import app

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]


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
    assert not [
        path for path in web_app.rglob("*") if path.name.lower() == "kids"
    ]
    assert not [
        path
        for path in (REPOSITORY_ROOT / "web/tests").rglob("*")
        if "kids" in path.name.lower()
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
