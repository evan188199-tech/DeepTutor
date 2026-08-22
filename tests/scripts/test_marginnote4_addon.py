"""Build tests for the MarginNote 4 Add-on package."""

from __future__ import annotations

import importlib.util
import json
import struct
from pathlib import Path
import shutil
import zipfile

import pytest


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
            "runtime.js",
            "mnutils.js",
            "mnnote.js",
            "LICENSE",
            "assets/dot.png",
            "data/en.json",
            "data/zh.json",
            "addonlib.lock.json",
        }
        assert b"DeepTutorMarginNote4 : JSExtension" in archive.read("main.js")
        assert b"MNConnection.fetchDev" in archive.read("network.js")
        assert b"NSURLConnection" not in archive.read("network.js")
        assert b"MbModelTool" not in archive.read("main.js")
        assert b"pairDevice" in archive.read("main.js")
        assert b"showPairPanel" in archive.read("main.js")
        assert b"UITextField" in archive.read("main.js")
        assert b"confirmPairPanel" in archive.read("main.js")
        assert b"app.studyController(this.window)" in archive.read("main.js")
        assert b"hostView.addSubview(overlay)" in archive.read("main.js")
        assert b"MNUtil.userInput" not in archive.read("main.js")
        assert b"UIAlertView" not in archive.read("main.js")
        assert b"pairFromClipboard" not in archive.read("main.js")

        icon = archive.read("deeptutor.png")
        assert icon.startswith(b"\x89PNG\r\n\x1a\n")
        assert struct.unpack(">II", icon[16:24]) == (44, 44)

        lock = json.loads(archive.read("addonlib.lock.json"))
        assert lock["locked_commit"] == "a9066fdc02449618ea022f07991bdfffee86cb3d"


def test_addon_package_build_is_reproducible(tmp_path: Path) -> None:
    builder = _builder()
    first = builder.build(tmp_path / "first.mnaddon")
    second = builder.build(tmp_path / "second.mnaddon")
    assert first.read_bytes() == second.read_bytes()


def test_addon_package_rejects_addonlib_hash_mismatch(tmp_path: Path) -> None:
    builder = _builder()
    original_source = builder._ADDONLIB
    tampered_source = tmp_path / "addonlib"
    shutil.copytree(original_source, tampered_source)
    (tampered_source / "runtime.js").write_text(
        (tampered_source / "runtime.js").read_text(encoding="utf-8") + "\n// tampered\n",
        encoding="utf-8",
    )
    builder._ADDONLIB = tampered_source
    try:
        with pytest.raises(ValueError, match="AddonLib hash mismatch for runtime.js"):
            builder.build(tmp_path / "invalid.mnaddon")
    finally:
        builder._ADDONLIB = original_source
