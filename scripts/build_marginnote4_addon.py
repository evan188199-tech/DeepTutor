"""Build the DeepTutor MarginNote 4 `.mnaddon` package."""

from __future__ import annotations

import base64
import json
from pathlib import Path
import tempfile
import zipfile

from deeptutor.runtime.home import PACKAGE_ROOT

_SOURCE = PACKAGE_ROOT / "packaging"
_ICON_PNG = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8AAAwAB/gFVZ1Q1AAAAAElFTkSuQmCC"
)


def build(output: Path | None = None) -> Path:
    """Return a zip archive with the manifest and JS files at package root."""
    manifest = json.loads((_SOURCE / "marginnote4_addon.mnaddon.json").read_text(encoding="utf-8"))
    target = output or (_SOURCE / "DeepTutorMarginNote4.mnaddon")
    target.parent.mkdir(parents=True, exist_ok=True)

    with tempfile.NamedTemporaryFile(suffix=".mnaddon") as temp_file:
        with zipfile.ZipFile(temp_file, "w", zipfile.ZIP_DEFLATED) as archive:
            archive.writestr(
                "mnaddon.json",
                json.dumps(manifest, ensure_ascii=False, indent=2),
            )
            archive.write(_SOURCE / "marginnote4_addon.main.js", arcname="main.js")
            archive.write(_SOURCE / "marginnote4_addon.network.js", arcname="network.js")
            archive.writestr("deeptutor.png", _ICON_PNG)
        temp_file.flush()
        target.write_bytes(Path(temp_file.name).read_bytes())
    return target


def main() -> int:
    path = build()
    print(path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
