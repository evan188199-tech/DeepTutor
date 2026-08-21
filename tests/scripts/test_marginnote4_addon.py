"""Build tests for the MarginNote 4 Add-on package."""

from __future__ import annotations

import importlib.util
from pathlib import Path
import zipfile


def _builder():
    path = Path(__file__).resolve().parents[2] / "scripts" / "build_marginnote4_addon.py"
    spec = importlib.util.spec_from_file_location("mn4_addon_builder", path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def test_addon_package_contains_expected_root_files(tmp_path: Path) -> None:
    output = _builder().build(tmp_path / "DeepTutorMarginNote4.mnaddon")
    with zipfile.ZipFile(output) as archive:
        assert set(archive.namelist()) == {
            "mnaddon.json",
            "main.js",
            "network.js",
            "deeptutor.png",
        }
        assert b"DeepTutorMarginNote4 : JSExtension" in archive.read("main.js")
        assert b"NSURLConnection" in archive.read("network.js")
