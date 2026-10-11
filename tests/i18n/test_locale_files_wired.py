"""Every locale JSON file on disk must be wired into ``web/i18n/init.ts``.

The web i18n runtime serves only the namespaces that ``init.ts`` imports.
A file under ``web/locales/<lang>/`` that no import references is dead
weight: translators maintain it, nothing serves it, and its keys silently
drift from the live copies in ``app.json`` (this is how four ``common.json``
copies accumulated 148 unserved key instances before the 2026-10-11
cleanup). This test fails whenever such an orphan file reappears.
"""

from __future__ import annotations

import pathlib
import re

WEB = pathlib.Path(__file__).resolve().parents[2] / "web"
INIT_TS = WEB / "i18n" / "init.ts"

# Matches both the eager ``import enApp from "@/locales/en/app.json"`` and
# the per-language dynamic ``import("@/locales/zh/app.json")`` specifiers.
_WIRED_IMPORT_RE = re.compile(r"@/locales/([a-z]{2})/([A-Za-z0-9_-]+)\.json")


def _wired_files() -> set[tuple[str, str]]:
    return {
        (lang, f"{name}.json")
        for lang, name in _WIRED_IMPORT_RE.findall(INIT_TS.read_text(encoding="utf-8"))
    }


def _locale_files_on_disk() -> set[tuple[str, str]]:
    return {
        (path.parent.name, path.name)
        for path in sorted((WEB / "locales").glob("*/[a-z]*.json"))
    }


def test_init_ts_actually_wires_locale_files() -> None:
    wired = _wired_files()
    assert wired, "web/i18n/init.ts must reference at least one locale file"


def test_every_locale_file_on_disk_is_wired() -> None:
    on_disk = _locale_files_on_disk()
    assert on_disk, "web/locales must contain at least one locale file"

    orphans = sorted(on_disk - _wired_files())
    assert not orphans, (
        "locale files exist on disk but are never loaded by web/i18n/init.ts; "
        f"wire them in or delete them: {orphans}"
    )


def test_every_wired_locale_file_exists_on_disk() -> None:
    missing = sorted(_wired_files() - _locale_files_on_disk())
    assert not missing, (
        "web/i18n/init.ts references locale files that do not exist: "
        f"{missing}"
    )
