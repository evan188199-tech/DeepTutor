#!/usr/bin/env python3
"""Migrate a nested immersive-reading data tree without destructive writes."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import shutil
from typing import Any


def _read_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return value if isinstance(value, dict) else {}


def _copy_preserving(source: Path, destination: Path, run_id: str) -> dict[str, str]:
    destination.parent.mkdir(parents=True, exist_ok=True)
    if not destination.exists():
        shutil.copy2(source, destination)
        return {"action": "copy", "source": str(source), "target": str(destination)}
    conflict = destination.with_name(f"{destination.name}.nested-{run_id}")
    shutil.copy2(source, conflict)
    return {
        "action": "conflict-copy",
        "source": str(source),
        "target": str(conflict),
        "existing": str(destination),
    }


def _copy_tree(source: Path, destination: Path, run_id: str) -> list[dict[str, str]]:
    if source.is_file():
        return [_copy_preserving(source, destination, run_id)]
    if not destination.exists():
        shutil.copytree(source, destination)
        return [{"action": "copy-tree", "source": str(source), "target": str(destination)}]
    actions: list[dict[str, str]] = []
    for item in source.iterdir():
        actions.extend(_copy_tree(item, destination / item.name, run_id))
    if not actions:
        return [{"action": "skip-identical-tree", "source": str(source)}]
    return actions


def _pair_key(pairing: dict[str, Any]) -> tuple[str, str]:
    return (
        str(pairing.get("en_document_id", "")),
        str(pairing.get("zh_document_id", "")),
    )


def migrate(
    source: Path,
    destination: Path,
    backup_root: Path,
    requested_ids: set[str],
) -> dict[str, Any]:
    if not source.is_dir():
        raise SystemExit(f"Nested data tree does not exist: {source}")

    source_settings = source / "settings"
    source_immersive = source / "workspace" / "immersive_reading"
    target_settings = destination / "settings"
    target_immersive = destination / "workspace" / "immersive_reading"
    source_documents = sorted(source_immersive.glob("document_*"))
    source_pairings = sorted((source_immersive / "bilingual").glob("pairing_*"))
    target_document_ids = {path.name for path in target_immersive.glob("document_*")}
    target_pairings = list((target_immersive / "bilingual").glob("pairing_*"))
    target_pair_keys = {_pair_key(_read_json(path / "pairing.json")) for path in target_pairings}

    backup_root.mkdir(parents=True, exist_ok=True)
    run_id = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    preflight = {
        "source": str(source),
        "destination": str(destination),
        "documents": [path.name for path in source_documents],
        "pairings": [path.name for path in source_pairings],
        "requested_ids": sorted(requested_ids),
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    (backup_root / "preflight-manifest.json").write_text(
        json.dumps(preflight, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    backup_source = backup_root / "source"
    if not backup_source.exists():
        shutil.copytree(source, backup_source)

    actions: list[dict[str, str]] = []
    settings = (
        sorted(path for path in source_settings.iterdir() if path.is_file())
        if source_settings.is_dir()
        else []
    )
    for path in settings:
        target = target_settings / path.name
        if target.exists():
            actions.append(
                {"action": "skip-existing-setting", "source": str(path), "target": str(target)}
            )
        else:
            shutil.copy2(path, target)
            actions.append({"action": "copy-setting", "source": str(path), "target": str(target)})

    for path in source_documents:
        if path.name in target_document_ids:
            actions.extend(_copy_tree(path, target_immersive / path.name, run_id))
        else:
            shutil.copytree(path, target_immersive / path.name)
            actions.append(
                {
                    "action": "copy-document",
                    "source": str(path),
                    "target": str(target_immersive / path.name),
                }
            )

    for path in source_pairings:
        key = _pair_key(_read_json(path / "pairing.json"))
        if key in target_pair_keys:
            actions.append(
                {"action": "skip-duplicate-pairing", "source": str(path), "pair": "/".join(key)}
            )
            continue
        shutil.copytree(path, target_immersive / "bilingual" / path.name)
        actions.append(
            {
                "action": "copy-pairing",
                "source": str(path),
                "target": str(target_immersive / "bilingual" / path.name),
            }
        )
        target_pair_keys.add(key)

    known_ids = (
        {path.name.removeprefix("document_") for path in source_documents}
        | {path.name.removeprefix("pairing_") for path in source_pairings}
        | {path.name.removeprefix("document_") for path in target_immersive.glob("document_*")}
        | {path.name.removeprefix("pairing_") for path in target_pairings}
    )
    report = {
        **preflight,
        "backup_root": str(backup_root),
        "requested_ids_found": sorted(requested_ids & known_ids),
        "actions": actions,
    }
    (backup_root / "migration-manifest.json").write_text(
        json.dumps(report, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    return report


def main() -> int:
    project_root = Path(__file__).resolve().parents[1]
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, default=project_root / "data/user/data/user")
    parser.add_argument("--destination", type=Path, default=project_root / "data/user")
    parser.add_argument("--backup-root", type=Path, default=None)
    parser.add_argument("--find-id", action="append", default=[])
    args = parser.parse_args()

    run = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    backup_root = args.backup_root or args.destination / "backups" / "nested-runtime"
    report = migrate(
        args.source.resolve(),
        args.destination.resolve(),
        (backup_root / run).resolve(),
        set(args.find_id),
    )
    print(json.dumps(report, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
