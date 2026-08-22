"""Build the DeepTutor MarginNote 4 `.mnaddon` package."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
import sys
import tempfile
import zipfile

_REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
if str(_REPOSITORY_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPOSITORY_ROOT))

_SOURCE = _REPOSITORY_ROOT / "packaging"
_ADDONLIB = _SOURCE / "vendor" / "addonlib"
_ADDONLIB_LOCK = _SOURCE / "addonlib.lock.json"
_FIXED_ZIP_TIME = (2026, 4, 4, 0, 0, 0)
_ICON_PNG = _SOURCE / "deeptutor.png"


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _validate_addonlib() -> dict[str, str]:
    lock = json.loads(_ADDONLIB_LOCK.read_text(encoding="utf-8"))
    locked_files = lock["files"]
    actual_files = {
        str(path.relative_to(_ADDONLIB))
        for path in _ADDONLIB.rglob("*")
        if path.is_file()
    }
    if actual_files != set(locked_files):
        raise ValueError(
            "AddonLib vendor contents do not match lockfile: "
            f"unexpected={sorted(actual_files - set(locked_files))}, "
            f"missing={sorted(set(locked_files) - actual_files)}"
        )
    for relative_path, expected_hash in locked_files.items():
        actual_hash = _sha256(_ADDONLIB / relative_path)
        if actual_hash != expected_hash:
            raise ValueError(
                f"AddonLib hash mismatch for {relative_path}: "
                f"expected {expected_hash}, got {actual_hash}"
            )
    return locked_files


def _write_file(archive: zipfile.ZipFile, source: Path, arcname: str) -> None:
    info = zipfile.ZipInfo(arcname, date_time=_FIXED_ZIP_TIME)
    info.compress_type = zipfile.ZIP_DEFLATED
    info.external_attr = 0o100644 << 16
    archive.writestr(info, source.read_bytes())


def _write_text(archive: zipfile.ZipFile, text: str, arcname: str) -> None:
    _write_zip_data(archive, text.encode("utf-8"), arcname)


def _write_bytes(archive: zipfile.ZipFile, data: bytes, arcname: str) -> None:
    _write_zip_data(archive, data, arcname)


def _write_zip_data(archive: zipfile.ZipFile, data: bytes | str, arcname: str) -> None:
    info = zipfile.ZipInfo(arcname, date_time=_FIXED_ZIP_TIME)
    info.compress_type = zipfile.ZIP_DEFLATED
    info.external_attr = 0o100644 << 16
    archive.writestr(info, data)


def build(output: Path | None = None) -> Path:
    """Return a zip archive with the manifest and JS files at package root."""
    _validate_addonlib()
    manifest = json.loads((_SOURCE / "marginnote4_addon.mnaddon.json").read_text(encoding="utf-8"))
    target = output or (_SOURCE / "DeepTutorMarginNote4.mnaddon")
    target.parent.mkdir(parents=True, exist_ok=True)

    with tempfile.NamedTemporaryFile(suffix=".mnaddon") as temp_file:
        with zipfile.ZipFile(temp_file, "w", zipfile.ZIP_DEFLATED) as archive:
            _write_text(
                archive,
                json.dumps(manifest, ensure_ascii=False, indent=2),
                "mnaddon.json",
            )
            _write_file(archive, _SOURCE / "marginnote4_addon.main.js", "main.js")
            _write_file(archive, _SOURCE / "marginnote4_addon.network.js", "network.js")
            _write_file(archive, _ICON_PNG, "deeptutor.png")
            for relative_path in (
                "runtime.js",
                "mnutils.js",
                "mnnote.js",
                "LICENSE",
                "assets/dot.png",
                "data/en.json",
                "data/zh.json",
            ):
                _write_file(archive, _ADDONLIB / relative_path, relative_path)
            _write_file(archive, _ADDONLIB_LOCK, "addonlib.lock.json")
        temp_file.flush()
        target.write_bytes(Path(temp_file.name).read_bytes())
    return target


def main() -> int:
    path = build()
    print(path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
