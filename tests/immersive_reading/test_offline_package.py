"""Offline package export tests."""

from __future__ import annotations

import json
import zipfile

import pytest

from deeptutor.immersive_reading.service import ImmersiveReadingService


def test_export_offline_package_creates_zip_with_required_files(
    reading_service: ImmersiveReadingService, imported_document: dict
) -> None:
    package_path = reading_service.export_offline_package(imported_document["id"])

    assert package_path.is_file()
    assert package_path.suffix == ".zip"
    with zipfile.ZipFile(package_path, "r") as archive:
        assert archive.testzip() is None
        names = archive.namelist()

    assert "manifest.json" in names
    assert "progress.json" in names
    assert "translations.json" in names
    assert "ecdict_subset.json" in names
    assert any(name.startswith("sections/") for name in names)
    with zipfile.ZipFile(package_path, "r") as archive:
        manifest = json.loads(archive.read("manifest.json"))
        assert manifest["id"] == imported_document["id"]
        assert json.loads(archive.read("translations.json")) == []
        assert json.loads(archive.read("ecdict_subset.json")) == []


def test_export_offline_package_rejects_missing_document(
    reading_service: ImmersiveReadingService,
) -> None:
    with pytest.raises(ValueError, match="Reading document not found"):
        reading_service.export_offline_package("missing")
