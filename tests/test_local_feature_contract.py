"""Contract for fork-local features on the upstream v1.6.12 baseline."""

from __future__ import annotations

from pathlib import Path

from deeptutor.api.main import app


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
    assert not [
        path for path in web_app.rglob("*") if path.name.lower() == "kids"
    ]
    assert not [
        path
        for path in Path("web/tests").rglob("*")
        if "kids" in path.name.lower()
    ]

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
