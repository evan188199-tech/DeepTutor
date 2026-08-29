"""Private, owner-scoped YouTube browser sessions for subtitle retrieval.

The browser profile used here is deliberately never the user's normal Chrome
profile.  The only durable output of a login is a filtered cookie jar in the
owner secrets tree; paths, cookie values and CDP details never leave this
module.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import secrets
import shutil
import socket
import stat
import subprocess
import sys
import tempfile
import time
from typing import Any

import httpx

from deeptutor.multi_user.paths import owner_secrets_dir

_TTL_SECONDS = 10 * 60
_ALLOWED_DOMAINS = ("youtube.com", "google.com")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _is_allowed_domain(value: object) -> bool:
    domain = str(value or "").lower().lstrip(".").rstrip(".")
    return bool(domain) and any(domain == allowed or domain.endswith(f".{allowed}") for allowed in _ALLOWED_DOMAINS)


class YouTubeCookieStore:
    """Minimal filtered cookie jar stored under an owner-private directory."""

    @staticmethod
    def _dir(owner_id: str) -> Path:
        path = owner_secrets_dir(owner_id) / "private" / "youtube"
        path.mkdir(parents=True, exist_ok=True)
        os.chmod(path, stat.S_IRWXU)
        return path

    @classmethod
    def _path(cls, owner_id: str) -> Path:
        return cls._dir(owner_id) / "cookies.json"

    @classmethod
    def read(cls, owner_id: str) -> dict[str, Any] | None:
        try:
            payload = json.loads(cls._path(owner_id).read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return None
        if not isinstance(payload, dict) or not isinstance(payload.get("cookies"), list):
            return None
        return payload

    @classmethod
    def has_cookies(cls, owner_id: str) -> bool:
        payload = cls.read(owner_id)
        return bool(payload and payload.get("cookies"))

    @classmethod
    def save(cls, owner_id: str, cookies: list[dict[str, Any]]) -> bool:
        filtered = [
            {
                key: cookie.get(key)
                for key in ("name", "value", "domain", "path", "expires", "secure", "httpOnly", "sameSite")
            }
            for cookie in cookies
            if isinstance(cookie, dict)
            and str(cookie.get("name") or "")
            and _is_allowed_domain(cookie.get("domain"))
        ]
        if not filtered:
            return False
        path = cls._path(owner_id)
        tmp = path.with_name(f".{path.name}.{secrets.token_hex(8)}.tmp")
        payload = {"cookies": filtered, "validated_at": _now()}
        try:
            with tmp.open("w", encoding="utf-8") as handle:
                json.dump(payload, handle, ensure_ascii=False, separators=(",", ":"))
                handle.flush()
                os.fsync(handle.fileno())
            os.chmod(tmp, stat.S_IRUSR | stat.S_IWUSR)
            os.replace(tmp, path)
            os.chmod(path, stat.S_IRUSR | stat.S_IWUSR)
            return True
        finally:
            tmp.unlink(missing_ok=True)

    @classmethod
    def delete(cls, owner_id: str) -> None:
        cls._path(owner_id).unlink(missing_ok=True)

    @classmethod
    def write_cookiefile(cls, owner_id: str, directory: Path) -> Path | None:
        """Materialize a short-lived Netscape jar for yt-dlp only."""
        payload = cls.read(owner_id)
        cookies = payload.get("cookies") if payload else []
        if not isinstance(cookies, list):
            return None
        path = directory / "youtube-cookies.txt"
        lines = ["# Netscape HTTP Cookie File"]
        for cookie in cookies:
            if not isinstance(cookie, dict) or not _is_allowed_domain(cookie.get("domain")):
                continue
            domain = str(cookie.get("domain") or "").lstrip(".")
            if not domain:
                continue
            expires = cookie.get("expires")
            try:
                expires_value = int(float(expires)) if float(expires or 0) > 0 else 0
            except (TypeError, ValueError):
                expires_value = 0
            lines.append(
                "\t".join(
                    (
                        f".{domain}",
                        "TRUE",
                        str(cookie.get("path") or "/"),
                        "TRUE" if cookie.get("secure") else "FALSE",
                        str(expires_value),
                        str(cookie.get("name") or ""),
                        str(cookie.get("value") or ""),
                    )
                )
            )
        if len(lines) == 1:
            return None
        path.write_text("\n".join(lines) + "\n", encoding="utf-8")
        os.chmod(path, stat.S_IRUSR | stat.S_IWUSR)
        return path


class HostChromeSessionStore:
    """Per-owner opt-in for the host Mac's existing Chrome session.

    This stores only the owner's consent and validation timestamp.  Browser
    cookies are never copied or persisted by DeepTutor in this mode; yt-dlp
    asks Chrome's native cookie store for the YouTube request at fetch time.
    """

    @staticmethod
    def _path(owner_id: str) -> Path:
        return YouTubeCookieStore._dir(owner_id) / "host-chrome.json"

    @classmethod
    def enabled(cls, owner_id: str) -> bool:
        return bool(cls.metadata(owner_id))

    @classmethod
    def metadata(cls, owner_id: str) -> dict[str, Any] | None:
        try:
            payload = json.loads(cls._path(owner_id).read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return None
        return payload if isinstance(payload, dict) and payload.get("enabled") is True else None

    @classmethod
    def enable(cls, owner_id: str) -> None:
        path = cls._path(owner_id)
        tmp = path.with_name(f".{path.name}.{secrets.token_hex(8)}.tmp")
        try:
            with tmp.open("w", encoding="utf-8") as handle:
                json.dump({"enabled": True, "enabled_at": _now()}, handle, separators=(",", ":"))
                handle.flush()
                os.fsync(handle.fileno())
            os.chmod(tmp, stat.S_IRUSR | stat.S_IWUSR)
            os.replace(tmp, path)
            os.chmod(path, stat.S_IRUSR | stat.S_IWUSR)
        finally:
            tmp.unlink(missing_ok=True)

    @classmethod
    def delete(cls, owner_id: str) -> None:
        cls._path(owner_id).unlink(missing_ok=True)


def find_chrome() -> str | None:
    if sys.platform != "darwin":
        return None
    for candidate in (
        "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
        "/Applications/Chromium.app/Contents/MacOS/Chromium",
        "/Applications/Google Chrome Canary.app/Contents/MacOS/Google Chrome Canary",
    ):
        if os.path.isfile(candidate) and os.access(candidate, os.X_OK):
            return candidate
    return None


def _unused_loopback_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as listener:
        listener.bind(("127.0.0.1", 0))
        return int(listener.getsockname()[1])


def _activate_chrome() -> None:
    """Bring the dedicated login window forward after a remote click.

    The API commonly runs as a launch agent while the user clicks from an
    iPad.  Launching a process alone can leave its window behind the active
    desktop, which feels like the button did nothing.
    """
    if sys.platform != "darwin":
        return
    try:
        subprocess.Popen(
            ["/usr/bin/osascript", "-e", 'tell application "Google Chrome" to activate'],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            close_fds=True,
        )
    except OSError:
        # The isolated Chrome still works if macOS refuses foregrounding.
        pass


async def _cdp_cookies(port: int) -> list[dict[str, Any]]:
    try:
        async with httpx.AsyncClient(timeout=1.5) as client:
            info = (await client.get(f"http://127.0.0.1:{port}/json/version")).json()
        endpoint = str(info.get("webSocketDebuggerUrl") or "")
        if not endpoint:
            return []
        import websockets

        async with websockets.connect(endpoint, open_timeout=1.5, close_timeout=1.0) as connection:
            await connection.send(json.dumps({"id": 1, "method": "Network.getAllCookies"}))
            while True:
                result = json.loads(await asyncio.wait_for(connection.recv(), timeout=2.0))
                if result.get("id") == 1:
                    cookies = result.get("result", {}).get("cookies", [])
                    return [cookie for cookie in cookies if isinstance(cookie, dict)]
    except Exception:
        return []


class YouTubeLoginManager:
    """In-memory login operations. Operations disappear after process cleanup."""

    def __init__(self) -> None:
        self._lock = asyncio.Lock()
        self._operations: dict[str, dict[str, Any]] = {}

    async def connect(self, owner_id: str) -> dict[str, Any]:
        async with self._lock:
            await self._prune_locked()
            for operation in self._operations.values():
                if operation["owner_id"] == owner_id and operation["state"] == "connecting":
                    _activate_chrome()
                    return self._public(operation)
            binary = find_chrome()
            if not binary:
                return {"connection": "error", "helper_available": False, "last_error_code": "chrome_unavailable"}
            profile = Path(tempfile.mkdtemp(prefix="deeptutor-youtube-"))
            os.chmod(profile, stat.S_IRWXU)
            operation_id = secrets.token_hex(16)
            port = _unused_loopback_port()
            try:
                process = subprocess.Popen(
                    [
                        binary,
                        "--remote-debugging-address=127.0.0.1",
                        f"--remote-debugging-port={port}",
                        f"--user-data-dir={profile}",
                        "--no-first-run",
                        "--no-default-browser-check",
                        "--new-window",
                        "https://www.youtube.com/",
                    ],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    close_fds=True,
                )
            except OSError:
                shutil.rmtree(profile, ignore_errors=True)
                return {"connection": "error", "helper_available": True, "last_error_code": "chrome_launch_failed"}
            operation = {
                "operation_id": operation_id,
                "owner_id": owner_id,
                "state": "connecting",
                "started_at": _now(),
                "expires_at": time.monotonic() + _TTL_SECONDS,
                "port": port,
                "profile": profile,
                "process": process,
                "last_error_code": "",
            }
            self._operations[operation_id] = operation
            _activate_chrome()
            return self._public(operation)

    async def operation(self, owner_id: str, operation_id: str) -> dict[str, Any] | None:
        async with self._lock:
            await self._prune_locked()
            operation = self._operations.get(operation_id)
            if not operation or operation["owner_id"] != owner_id:
                return None
            if operation["state"] == "connecting":
                cookies = await _cdp_cookies(int(operation["port"]))
                if YouTubeCookieStore.save(owner_id, cookies):
                    operation["state"] = "connected"
                    await self._cleanup_locked(operation)
            return self._public(operation)

    async def status(self, owner_id: str) -> dict[str, Any]:
        async with self._lock:
            await self._prune_locked()
            active = next((op for op in self._operations.values() if op["owner_id"] == owner_id and op["state"] == "connecting"), None)
            saved = YouTubeCookieStore.read(owner_id)
            host_chrome = HostChromeSessionStore.metadata(owner_id)
            helper_available = bool(find_chrome())
            connection = "connecting" if active else ("connected" if saved or (host_chrome and helper_available) else ("error" if host_chrome else "disconnected"))
            return {
                "connection": connection,
                "helper_available": helper_available,
                "last_validated_at": str((saved or {}).get("validated_at") or (host_chrome or {}).get("enabled_at") or "") or None,
                "last_error_code": str((active or {}).get("last_error_code") or ("chrome_unavailable" if host_chrome and not helper_available else "")) or None,
                "next_prefetch_at": None,
            }

    async def disconnect(self, owner_id: str) -> None:
        async with self._lock:
            for operation in list(self._operations.values()):
                if operation["owner_id"] == owner_id:
                    await self._cleanup_locked(operation)
                    self._operations.pop(operation["operation_id"], None)
            YouTubeCookieStore.delete(owner_id)

    async def _prune_locked(self) -> None:
        now = time.monotonic()
        for operation_id, operation in list(self._operations.items()):
            if operation["state"] == "connecting" and operation["expires_at"] < now:
                operation["state"] = "expired"
                operation["last_error_code"] = "login_expired"
                await self._cleanup_locked(operation)
            if operation["state"] in {"connected", "expired"}:
                # Preserve a just-completed operation long enough for its polling response.
                if now - float(operation["expires_at"]) > 60:
                    self._operations.pop(operation_id, None)

    async def _cleanup_locked(self, operation: dict[str, Any]) -> None:
        process = operation.get("process")
        if process is not None and process.poll() is None:
            process.terminate()
            try:
                await asyncio.to_thread(process.wait, 2)
            except Exception:
                process.kill()
        profile = operation.get("profile")
        if isinstance(profile, Path):
            await asyncio.to_thread(shutil.rmtree, profile, True)

    @staticmethod
    def _public(operation: dict[str, Any]) -> dict[str, Any]:
        return {
            "operation_id": operation["operation_id"],
            "connection": operation["state"],
            "helper_available": bool(find_chrome()),
            "last_error_code": operation.get("last_error_code") or None,
        }


_manager: YouTubeLoginManager | None = None


def get_youtube_login_manager() -> YouTubeLoginManager:
    global _manager
    if _manager is None:
        _manager = YouTubeLoginManager()
    return _manager
