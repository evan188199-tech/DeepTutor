"""Interface settings store: read/write round-trips, raw merges, atomic writes."""

from __future__ import annotations

import json
from pathlib import Path
import threading

import pytest

from deeptutor.services.settings import interface_settings
from deeptutor.tools.builtin import USER_TOGGLEABLE_TOOL_NAMES


@pytest.fixture
def settings_file(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    path = tmp_path / "settings" / "interface.json"
    monkeypatch.setattr(interface_settings, "_interface_settings_file", lambda: path)
    return path


# --- Read/write round-trip -------------------------------------------------


def test_defaults_when_no_file_exists(settings_file: Path) -> None:
    assert interface_settings.get_ui_settings() == interface_settings.DEFAULT_UI_SETTINGS
    assert not settings_file.exists()


def test_round_trip_set_then_get(settings_file: Path) -> None:
    stored = interface_settings.set_ui_setting("theme", "midnight")

    assert json.loads(settings_file.read_text(encoding="utf-8"))["theme"] == "midnight"
    view = interface_settings.get_ui_settings()
    assert view["theme"] == "midnight"
    assert view == {**interface_settings.DEFAULT_UI_SETTINGS, "theme": "midnight"}
    assert stored == json.loads(settings_file.read_text(encoding="utf-8"))


def test_update_keeps_other_fields(settings_file: Path) -> None:
    interface_settings.update_ui_settings({"theme": "midnight", "custom_key": "keep-me"})

    interface_settings.update_ui_settings({"language": "zh"})

    stored = json.loads(settings_file.read_text(encoding="utf-8"))
    assert stored["theme"] == "midnight"
    assert stored["custom_key"] == "keep-me"
    assert stored["language"] == "zh"
    assert interface_settings.get_ui_settings()["language"] == "zh"


def test_update_merges_into_raw_stored_not_the_defaults_view(settings_file: Path) -> None:
    """A merge must not materialise today's defaults as the user's explicit choices.

    ``get_ui_settings`` returns a defaults-merged view; writing that back would
    freeze every default, so a user who once changed their theme would silently
    stop following later changes to any other default.
    """
    interface_settings.update_ui_settings({"theme": "midnight"})

    stored = json.loads(settings_file.read_text(encoding="utf-8"))
    assert stored == {"theme": "midnight"}
    assert set(interface_settings.DEFAULT_UI_SETTINGS) - {"theme"} - set(stored)


def test_replace_wholesale_resets_previous_fields(settings_file: Path) -> None:
    interface_settings.update_ui_settings({"theme": "midnight", "custom_key": "gone"})

    stored = interface_settings.replace_ui_settings({"language": "fr"})

    assert stored == {"language": "fr"}
    # response_language inherits the interface language on a file written
    # before the split (resolve_languages runs on every read).
    assert interface_settings.get_ui_settings() == {
        **interface_settings.DEFAULT_UI_SETTINGS,
        "language": "fr",
        "response_language": "fr",
    }


def test_corrupt_file_reads_as_defaults(settings_file: Path) -> None:
    settings_file.parent.mkdir(parents=True, exist_ok=True)
    settings_file.write_text("{not json", encoding="utf-8")

    assert interface_settings.get_ui_settings() == interface_settings.DEFAULT_UI_SETTINGS


def test_non_dict_file_reads_as_defaults(settings_file: Path) -> None:
    settings_file.parent.mkdir(parents=True, exist_ok=True)
    settings_file.write_text("[1, 2, 3]", encoding="utf-8")

    assert interface_settings.get_ui_settings() == interface_settings.DEFAULT_UI_SETTINGS


# --- Language resolution ----------------------------------------------------


def test_resolve_languages_legacy_file_inherits_interface_language() -> None:
    assert interface_settings.resolve_languages({"language": "zh"}) == {
        "language": "zh",
        "response_language": "zh",
    }


def test_resolve_languages_missing_and_junk_fall_back() -> None:
    resolved = interface_settings.resolve_languages(
        {"language": "klingon", "response_language": ""}
    )

    assert resolved == {"language": "en", "response_language": "en"}


# --- Optional-tool sanitising ------------------------------------------------


def test_sanitize_enabled_tools_rejects_non_lists() -> None:
    assert interface_settings.sanitize_enabled_tools(None) == list(USER_TOGGLEABLE_TOOL_NAMES)
    assert interface_settings.sanitize_enabled_tools("web_search") == list(
        USER_TOGGLEABLE_TOOL_NAMES
    )


def test_sanitize_enabled_tools_dedupes_and_drops_unknown_names() -> None:
    result = interface_settings.sanitize_enabled_tools(
        ["web_search", "not_a_real_tool", "web_search", 42, "reason"]
    )

    assert result == ["web_search", "reason"]


# --- atomic_update -----------------------------------------------------------


def test_atomic_update_replaces_a_corrupt_file(settings_file: Path) -> None:
    settings_file.parent.mkdir(parents=True, exist_ok=True)
    settings_file.write_text("{not json", encoding="utf-8")

    stored = interface_settings.atomic_update(settings_file, lambda _stored: {"theme": "dark"})

    assert stored == {"theme": "dark"}
    assert json.loads(settings_file.read_text(encoding="utf-8")) == {"theme": "dark"}


def test_atomic_update_replaces_a_non_dict_file(settings_file: Path) -> None:
    settings_file.parent.mkdir(parents=True, exist_ok=True)
    settings_file.write_text('"just a string"', encoding="utf-8")

    interface_settings.atomic_update(settings_file, lambda _stored: {"theme": "dark"})

    assert json.loads(settings_file.read_text(encoding="utf-8")) == {"theme": "dark"}


def test_atomic_update_creates_missing_parent_directories(tmp_path: Path) -> None:
    target = tmp_path / "a" / "b" / "interface.json"

    interface_settings.atomic_update(target, lambda _stored: {"theme": "dark"})

    assert json.loads(target.read_text(encoding="utf-8")) == {"theme": "dark"}


def test_atomic_update_returns_what_is_on_disk(settings_file: Path) -> None:
    def _mutate(stored: dict) -> dict:
        stored["seen_by_mutate"] = bool(stored)
        return stored

    stored = interface_settings.atomic_update(settings_file, _mutate)

    assert stored == {"seen_by_mutate": False}
    assert json.loads(settings_file.read_text(encoding="utf-8")) == stored


def test_failed_mutate_leaves_previous_file_and_no_temp_files(settings_file: Path) -> None:
    interface_settings.atomic_update(settings_file, lambda _stored: {"theme": "keep"})

    def _boom(_stored: dict) -> dict:
        raise RuntimeError("mutate failed")

    with pytest.raises(RuntimeError):
        interface_settings.atomic_update(settings_file, _boom)

    assert json.loads(settings_file.read_text(encoding="utf-8")) == {"theme": "keep"}
    assert list(settings_file.parent.glob(".interface.json.*.tmp")) == []


def test_successful_write_leaves_no_temp_files(settings_file: Path) -> None:
    interface_settings.atomic_update(settings_file, lambda _stored: {"theme": "dark"})

    assert list(settings_file.parent.glob(".interface.json.*.tmp")) == []
    assert settings_file.read_text(encoding="utf-8").endswith("}\n")


def test_lock_is_shared_per_path_and_distinct_across_paths(tmp_path: Path) -> None:
    a = tmp_path / "interface.json"
    b = tmp_path / "other.json"

    assert interface_settings._settings_lock(a) is interface_settings._settings_lock(a)
    assert interface_settings._settings_lock(a) is not interface_settings._settings_lock(b)
    assert interface_settings._settings_lock(a) is not interface_settings._settings_lock(
        tmp_path / "nested" / "interface.json"
    )


def test_concurrent_writers_all_land(settings_file: Path) -> None:
    """Every writer through ``atomic_update`` must survive every other writer.

    Writers share one lock per file — the workspace manifest service and the
    settings router both call this primitive on shared files — so all N fields
    have to land and the file must stay valid JSON throughout.
    """
    threads_count = 12
    writes_per_thread = 25
    errors: list[BaseException] = []

    def writer(index: int) -> None:
        try:
            for round_index in range(writes_per_thread):
                interface_settings.update_ui_settings({f"writer_{index}": round_index})
        except BaseException as exc:  # surfaced below so the thread joins cleanly
            errors.append(exc)

    threads = [threading.Thread(target=writer, args=(i,)) for i in range(threads_count)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert errors == []
    stored = json.loads(settings_file.read_text(encoding="utf-8"))
    assert set(stored) == {f"writer_{i}" for i in range(threads_count)}
    assert all(stored[f"writer_{i}"] == writes_per_thread - 1 for i in range(threads_count))
    assert list(settings_file.parent.glob(".interface.json.*.tmp")) == []
