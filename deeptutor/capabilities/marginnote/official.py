"""Probe official MarginNote 4 interfaces. Never write to Realm."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from pathlib import Path
import shutil
import subprocess
from typing import Any

MN4_APP_CANDIDATES = (
    Path("/Applications/MarginNote 4.app"),
    Path("/Applications/MarginNote4.app"),
    Path.home() / "Applications" / "MarginNote 4.app",
    Path.home() / "Applications" / "MarginNote4.app",
)
URL_SCHEMES = ("marginnote4://", "marginnote://")


@dataclass(slots=True)
class OfficialWriteProbe:
    app_present: bool = False
    app_path: str = ""
    url_scheme_registered: bool = False
    write_api_verified: bool = False
    write_api_name: str = ""
    block_reason: str = (
        "No official MN4 write API has been verified on this Mac. "
        "DeepTutor will queue notes for the user to import."
    )
    evidence: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        if self.app_path:
            payload["app_path"] = Path(self.app_path).name
        return payload


def _looks_like_mn4_app(path: Path) -> bool:
    name = path.name.lower()
    return path.is_dir() and "marginnote" in name and name.endswith(".app")


def _find_mn4_app() -> Path | None:
    for candidate in MN4_APP_CANDIDATES:
        try:
            if _looks_like_mn4_app(candidate):
                return candidate
        except OSError:
            continue
    mdfind = shutil.which("mdfind")
    if not mdfind:
        return None
    try:
        completed = subprocess.run(
            [mdfind, "kMDItemCFBundleIdentifier == 'com.marginnote.MarginNote4'"],
            check=False,
            capture_output=True,
            text=True,
            timeout=3,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    for line in completed.stdout.splitlines():
        path = Path(line.strip())
        if _looks_like_mn4_app(path):
            return path
    return None


def _scheme_registered(scheme: str) -> bool:
    python = shutil.which("python3")
    if not python:
        return False
    script = (
        "from AppKit import NSWorkspace\n"
        "from Foundation import NSURL\n"
        f"url = NSURL.URLWithString_({scheme!r})\n"
        "print(bool(NSWorkspace.sharedWorkspace().URLForApplicationToOpenURL_(url)))\n"
    )
    try:
        completed = subprocess.run(
            [python, "-c", script],
            check=False,
            capture_output=True,
            text=True,
            timeout=3,
        )
    except (OSError, subprocess.TimeoutExpired):
        return False
    return completed.returncode == 0 and "True" in (completed.stdout or "")


def probe_official_write_interface() -> OfficialWriteProbe:
    """Inspect this Mac for a verified official write path.

    Finding the app or a URL scheme is not enough to claim write-back.
    """
    result = OfficialWriteProbe()
    app = _find_mn4_app()
    if app is not None:
        result.app_present = True
        result.app_path = str(app)
        result.evidence.append("mn4_app_present")
    for scheme in URL_SCHEMES:
        if _scheme_registered(scheme):
            result.url_scheme_registered = True
            result.evidence.append("url_scheme:" + scheme)
            break
    result.write_api_verified = False
    if result.app_present and result.url_scheme_registered:
        result.block_reason = (
            "MarginNote 4 is installed and a URL scheme is registered, but no "
            "official write/import API has been verified. Writes stay in the import queue."
        )
    elif result.app_present:
        result.block_reason = (
            "MarginNote 4 is installed, but no official write API is verified. "
            "Writes stay in the import queue."
        )
    return result


__all__ = ["OfficialWriteProbe", "probe_official_write_interface"]
