"""MarkItDown version and built-in input-format compatibility helpers."""

from __future__ import annotations

from functools import lru_cache
import importlib
import logging
import pkgutil

from .._versions import package_version, version_at_least

logger = logging.getLogger(__name__)

MIN_MARKITDOWN_VERSION = "0.1.7"

# Built-in local converters shipped by MarkItDown 0.1.7. Azure Content
# Understanding formats are intentionally excluded because DeepTutor's local
# adapter does not configure that billable cloud service.
MARKITDOWN_0_1_7_FORMATS = frozenset(
    {
        ".atom",
        ".csv",
        ".docx",
        ".epub",
        ".html",
        ".htm",
        ".ipynb",
        ".jpeg",
        ".jpg",
        ".json",
        ".jsonl",
        ".m4a",
        ".markdown",
        ".md",
        ".mp3",
        ".mp4",
        ".msg",
        ".pdf",
        ".png",
        ".pptx",
        ".rss",
        ".text",
        ".txt",
        ".wav",
        ".xls",
        ".xlsx",
        ".xml",
        ".zip",
    }
)


def _normalize_extensions(values: object) -> set[str]:
    if not isinstance(values, (list, tuple, set, frozenset)):
        return set()
    normalized: set[str] = set()
    for value in values:
        extension = str(value or "").strip().lower()
        if extension:
            normalized.add(extension if extension.startswith(".") else f".{extension}")
    return normalized


_DETECTION_FAILURES: list[str] = []


def _detect_converter_formats() -> tuple[set[str], list[str]]:
    """Inspect installed converter modules for extension constants.

    Import breakage is reported instead of raised so the upload allow set can
    still degrade to the 0.1.7 floor; each failure is also logged by the
    caller so a stale set leaves a trace.
    """
    discovered: set[str] = set()
    failures: list[str] = []
    try:
        converters = importlib.import_module("markitdown.converters")
    except Exception as exc:  # noqa: BLE001 - any import break degrades detection
        failures.append(f"markitdown.converters import failed: {exc!r}")
        return discovered, failures
    paths = getattr(converters, "__path__", ())
    if not paths:
        failures.append("markitdown.converters exposed no package path")
        return discovered, failures
    module_infos = list(pkgutil.iter_modules(paths, f"{converters.__name__}."))
    if not module_infos:
        failures.append("markitdown.converters exposed no converter modules")
        return discovered, failures
    for module_info in module_infos:
        try:
            module = importlib.import_module(module_info.name)
        except Exception as exc:  # noqa: BLE001 - one broken module drops only its formats
            failures.append(f"{module_info.name} import failed: {exc!r}")
            continue
        for name in dir(module):
            if "EXTENSION" not in name.upper():
                continue
            discovered.update(_normalize_extensions(getattr(module, name, None)))
    return discovered, failures


@lru_cache(maxsize=1)
def markitdown_supported_formats() -> frozenset[str]:
    """Return the current installed converter extensions plus the 0.1.7 floor.

    Converter modules expose extension constants. Inspecting them means a
    future compatible MarkItDown release can add a built-in type without
    waiting for a DeepTutor release. When detection fails the result degrades
    to the well-defined ``MARKITDOWN_0_1_7_FORMATS`` floor: every failure is
    logged as a warning and reported by
    :func:`markitdown_format_detection_failures`.
    """
    global _DETECTION_FAILURES
    discovered, failures = _detect_converter_formats()
    _DETECTION_FAILURES = failures
    for failure in failures:
        logger.warning("markitdown format detection degraded: %s", failure)
    return MARKITDOWN_0_1_7_FORMATS | frozenset(discovered)


def markitdown_format_detection_failures() -> tuple[str, ...]:
    """Return detection failures from the latest supported-formats probe.

    Empty when the installed converters were inspected cleanly. Callers (and
    tests) use this to tell a healthy detection apart from a degraded one.
    """
    markitdown_supported_formats()
    return tuple(_DETECTION_FAILURES)


def installed_markitdown_version() -> str:
    return package_version("markitdown")


def markitdown_version_is_current(version: str | None = None) -> bool:
    current = installed_markitdown_version() if version is None else version
    return version_at_least(current, MIN_MARKITDOWN_VERSION)


__all__ = [
    "MARKITDOWN_0_1_7_FORMATS",
    "MIN_MARKITDOWN_VERSION",
    "installed_markitdown_version",
    "markitdown_format_detection_failures",
    "markitdown_supported_formats",
    "markitdown_version_is_current",
]
