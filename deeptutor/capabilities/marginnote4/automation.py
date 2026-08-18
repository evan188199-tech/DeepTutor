"""Verified macOS automation providers for MarginNote 4."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import asdict, dataclass, field
import hashlib
import json
from pathlib import Path
import plistlib
import shutil
import subprocess
from typing import Any, Callable
from urllib.parse import quote
from xml.etree import ElementTree as ET


class AutomationError(Exception):
    pass


@dataclass(slots=True)
class ProbeResult:
    available: bool = False
    can_write: bool = False
    bundle_id: str = ""
    app_version: str = ""
    evidence: list[str] = field(default_factory=list)
    reason: str = ""


@dataclass(slots=True)
class WriteRequest:
    title: str
    markdown: str
    tags: list[str] = field(default_factory=list)
    target_notebook: str = ""


class AutomationProvider(ABC):
    name = "abstract"

    @abstractmethod
    def probe(self) -> ProbeResult: ...

    @abstractmethod
    def verify(self, *, test_note_title: str) -> ProbeResult: ...

    @abstractmethod
    def apply(self, request: WriteRequest) -> str:
        """Return an external ID or other durable evidence."""


def _run(
    command: list[str],
    *,
    timeout: int = 10,
    input_text: str | None = None,
    runner: Callable[..., subprocess.CompletedProcess[str]] | None = None,
) -> subprocess.CompletedProcess[str]:
    execute = runner or subprocess.run
    try:
        return execute(
            command,
            check=False,
            capture_output=True,
            text=True,
            timeout=timeout,
            input=input_text,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise AutomationError(str(exc)) from exc


def _local_tag(name: str) -> str:
    return name.rsplit("}", 1)[-1].lower()


def _applescript_string(value: str) -> str:
    escaped = (
        value.replace("\\", "\\\\")
        .replace('"', '\\"')
        .replace("\r", "\\r")
        .replace("\n", "\\n")
        .replace("\t", "\\t")
    )
    return f'"{escaped}"'


class _TemplateValues(dict[str, str]):
    def __missing__(self, key: str) -> str:
        raise AutomationError(f"Unsupported template placeholder: {{{key}}}")


class AppleScriptProvider(AutomationProvider):
    """Discover real commands in MarginNote's AppleScript dictionary."""

    name = "applescript"

    def __init__(
        self,
        app_path: str = "/Applications/MarginNote 4.app",
        script_template: str = "",
        runner: Callable[..., subprocess.CompletedProcess[str]] | None = None,
    ) -> None:
        self.app_path = Path(app_path).expanduser()
        self.script_template = script_template.strip()
        self.runner = runner

    def probe(self) -> ProbeResult:
        result = ProbeResult(reason="MarginNote application was not found")
        if not self.app_path.is_dir():
            return result
        result.available = True
        result.evidence.append("app_present")
        info_path = self.app_path / "Contents" / "Info.plist"
        try:
            with info_path.open("rb") as handle:
                info = plistlib.load(handle)
        except (OSError, plistlib.InvalidFileException) as exc:
            result.reason = f"Could not read Info.plist: {exc}"
            return result
        result.bundle_id = str(info.get("CFBundleIdentifier") or "")
        result.app_version = str(info.get("CFBundleShortVersionString") or "")
        sdef = shutil.which("sdef")
        if not sdef:
            result.reason = "sdef is unavailable"
            return result
        completed = _run([sdef, str(self.app_path)], timeout=10, runner=self.runner)
        if completed.returncode or not completed.stdout.strip():
            result.reason = "MarginNote did not expose an AppleScript dictionary"
            return result
        try:
            root = ET.fromstring(completed.stdout)
        except ET.ParseError as exc:
            result.reason = f"Invalid sdef XML: {exc}"
            return result
        commands: list[dict[str, Any]] = []
        for element in root.iter():
            if _local_tag(element.tag) != "command":
                continue
            name = element.attrib.get("name", "").lower()
            parameters = [
                parameter.attrib.get("name", "").lower()
                for parameter in element.iter()
                if _local_tag(parameter.tag) == "parameter"
            ]
            commands.append({"name": name, "parameters": parameters})
        create_like = [
            command
            for command in commands
            if command["name"] in {"make", "create", "new"}
            or "note" in command["name"]
            or "note" in command["parameters"]
        ]
        useful = [
            command
            for command in create_like
            if any(
                key in command["parameters"] for key in ("title", "name", "text", "content", "body")
            )
        ]
        result.evidence.extend(f"command:{command['name']}" for command in create_like)
        result.can_write = bool(useful)
        result.reason = "" if useful else "No title/body creation command was found"
        return result

    def verify(self, *, test_note_title: str) -> ProbeResult:
        result = self.probe()
        if not result.can_write or not self.script_template:
            result.reason = result.reason or "An explicit AppleScript template is required"
            result.can_write = False
            return result
        request = WriteRequest(
            title=test_note_title,
            markdown="DeepTutor MarginNote bridge verification note. This note may be deleted.",
        )
        try:
            self.apply(request)
            result.evidence.append("test_write_accepted")
        except AutomationError as exc:
            result.can_write = False
            result.reason = str(exc)
        return result

    def apply(self, request: WriteRequest) -> str:
        if not self.script_template:
            raise AutomationError("AppleScript template is not configured")
        values = _TemplateValues(
            title=_applescript_string(request.title),
            body=_applescript_string(request.markdown),
            notebook=_applescript_string(request.target_notebook),
        )
        try:
            script = self.script_template.format_map(values)
        except (KeyError, ValueError) as exc:
            raise AutomationError(f"Invalid AppleScript template: {exc}") from exc
        osascript = shutil.which("osascript")
        if not osascript:
            raise AutomationError("osascript is unavailable")
        completed = _run([osascript, "-e", script], runner=self.runner)
        if completed.returncode:
            raise AutomationError(completed.stderr.strip() or "AppleScript failed")
        return completed.stdout.strip()


class ShortcutProvider(AutomationProvider):
    name = "shortcut"

    def __init__(
        self,
        shortcut_name: str,
        runner: Callable[..., subprocess.CompletedProcess[str]] | None = None,
    ) -> None:
        self.shortcut_name = shortcut_name.strip()
        self.runner = runner

    def probe(self) -> ProbeResult:
        result = ProbeResult(reason="Shortcut name is required")
        shortcuts = shutil.which("shortcuts")
        if not shortcuts:
            result.reason = "shortcuts CLI is unavailable"
            return result
        if not self.shortcut_name:
            return result
        completed = _run(["shortcuts", "list"], timeout=10, runner=self.runner)
        if completed.returncode:
            result.reason = completed.stderr.strip() or "Could not list shortcuts"
            return result
        names = {line.strip() for line in completed.stdout.splitlines() if line.strip()}
        result.available = self.shortcut_name in names
        result.reason = "" if result.available else "Configured shortcut was not found"
        result.evidence.append("shortcuts_cli")
        return result

    def verify(self, *, test_note_title: str) -> ProbeResult:
        result = self.probe()
        result.can_write = result.available
        if not result.available:
            return result
        try:
            self.apply(
                WriteRequest(
                    title=test_note_title,
                    markdown="DeepTutor verification note. This note may be deleted.",
                )
            )
            result.evidence.append("fixed_json_protocol_accepted")
        except AutomationError as exc:
            result.can_write = False
            result.reason = str(exc)
        return result

    def apply(self, request: WriteRequest) -> str:
        shortcuts = shutil.which("shortcuts")
        if not shortcuts:
            raise AutomationError("shortcuts CLI is unavailable")
        payload = json.dumps(
            {
                "title": request.title,
                "markdown": request.markdown,
                "tags": request.tags,
                "targetNotebook": request.target_notebook,
            },
            ensure_ascii=False,
        )
        completed = _run(
            ["shortcuts", "run", self.shortcut_name],
            input_text=payload,
            runner=self.runner,
        )
        if completed.returncode:
            raise AutomationError(completed.stderr.strip() or "Shortcut failed")
        output = completed.stdout.strip()
        if output:
            try:
                decoded = json.loads(output)
                if not isinstance(decoded, dict) or decoded.get("ok") is not True:
                    raise AutomationError("Shortcut did not return {'ok': true}")
                return str(decoded.get("external_id") or "")
            except json.JSONDecodeError as exc:
                raise AutomationError(f"Shortcut output is not valid JSON: {exc}") from exc
        return ""


class URLSchemeProvider(AutomationProvider):
    """Only opens a user-configured, previously tested action template."""

    name = "url_scheme"

    def __init__(
        self,
        action_template: str = "",
        open_command: str = "",
        runner: Callable[..., subprocess.CompletedProcess[str]] | None = None,
    ) -> None:
        self.action_template = action_template.strip()
        self.open_command = open_command or shutil.which("open") or "open"
        self.runner = runner

    def probe(self) -> ProbeResult:
        result = ProbeResult(
            available=self.action_template.startswith("marginnote4://"),
            can_write=False,
            reason=(
                "URL action template is required"
                if not self.action_template
                else "Only marginnote4:// action templates are supported"
            ),
        )
        if result.available:
            result.reason = "URL registration alone does not verify a write action"
            result.evidence.append("configured_marginnote4_url")
        return result

    def verify(self, *, test_note_title: str) -> ProbeResult:
        result = self.probe()
        if not self.action_template:
            return result
        result.reason = "URL action template must be manually confirmed in MarginNote"
        result.evidence.append("human_confirmation_required")
        return result

    def apply(self, request: WriteRequest) -> str:
        if not self.action_template.startswith("marginnote4://"):
            raise AutomationError("URL action template is not configured")
        values = _TemplateValues(
            title=quote(request.title, safe=""),
            markdown=quote(request.markdown, safe=""),
            tags=quote(",".join(request.tags), safe=""),
            notebook=quote(request.target_notebook, safe=""),
        )
        try:
            url = self.action_template.format_map(values)
        except (KeyError, ValueError) as exc:
            raise AutomationError(f"Invalid URL action template: {exc}") from exc
        completed = _run([self.open_command, url], runner=self.runner)
        if completed.returncode:
            raise AutomationError(completed.stderr.strip() or "Could not open URL")
        return ""


def config_hash(provider: AutomationProvider) -> str:
    values: dict[str, Any]
    if isinstance(provider, AppleScriptProvider):
        values = {"app": str(provider.app_path), "script": provider.script_template}
    elif isinstance(provider, ShortcutProvider):
        values = {"shortcut": provider.shortcut_name}
    else:
        values = {"template": provider.action_template}
    return hashlib.sha256(json.dumps(values, sort_keys=True).encode()).hexdigest()


def provider_summary(result: ProbeResult) -> dict[str, Any]:
    return asdict(result)


__all__ = [
    "AppleScriptProvider",
    "AutomationError",
    "AutomationProvider",
    "ProbeResult",
    "ShortcutProvider",
    "URLSchemeProvider",
    "WriteRequest",
    "config_hash",
    "provider_summary",
]
