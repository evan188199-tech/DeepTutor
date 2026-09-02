"""Local-data migration commands."""

from __future__ import annotations

import json

import typer

from deeptutor.multi_user.legacy_kids_learner_migration import LegacyKidsLearnerMigration

from .common import console


def register(app: typer.Typer) -> None:
    migrate_app = typer.Typer(help="Migrate local legacy data.")
    app.add_typer(migrate_app, name="migrate")

    @migrate_app.command("legacy-kids")
    def legacy_kids(
        profile: str = typer.Option(..., "--profile", help="Exact legacy profile name."),
        apply: bool = typer.Option(
            False,
            "--apply",
            help="Write the migration. Without this flag only a dry-run is performed.",
        ),
    ) -> None:
        """Migrate one retired Kids profile into its existing learner account."""
        migration = LegacyKidsLearnerMigration(profile_name=profile)
        result = migration.apply() if apply else migration.plan()
        console.print_json(json.dumps(result, ensure_ascii=False, default=str))


__all__ = ["register"]
