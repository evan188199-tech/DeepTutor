"""Claude model-catalog sync behavior, fully offline.

The pty/TUI capture (:func:`_capture_model_screen`) is monkeypatched — no
``claude`` process is ever spawned — and the cache path is pointed at a temp
directory, so the suite exercises the picker parser, the cache read/write
contract, and every failure branch (capture exception, empty screen, unparseable
screen) without touching real settings files.
"""

from __future__ import annotations

import json

import pytest

from deeptutor.services.subagent import claude_models as cm

SCREEN = "\n".join(
    [
        "╭──────────────────────────╮",
        "│ Select Model",
        "╰──────────────────────────╯",
        "",
        "   1. Default   · Current model",
        "❯  2. Sonnet (recommended)   Recommended for daily use",
        "   3. Opus   Most capable · premium pricing",
        "   4. Opus [1m context]   Opus with a 1M window",
        "   5. haiku   Fastest · cheapest",
        "   6. Fable (disabled)   Experimental",
        "   7. Opus   duplicate tier",
        "",
        "Esc to cancel",
    ]
)


# ---- picker parser -------------------------------------------------------------


def test_parse_model_screen_maps_selectable_tiers() -> None:
    models = cm._parse_model_screen(SCREEN)
    assert models == [
        {"slug": "opus", "display_name": "Most capable"},
        {"slug": "opus[1m]", "display_name": "Opus with a 1M window"},
        {"slug": "haiku", "display_name": "Fastest"},
    ]


def test_parse_model_screen_ignores_rows_before_header_and_unparseable_screens() -> None:
    # rows before the header and a screen without the header yield nothing usable
    assert cm._parse_model_screen("   1. Opus   stray row") == []
    assert cm._parse_model_screen("") == []


# ---- cache read ----------------------------------------------------------------


def test_load_cached_models_missing_and_corrupt_files(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(cm, "_cache_path", lambda: tmp_path / "cache.json")
    assert cm.load_cached_claude_models() == ([], "")

    (tmp_path / "cache.json").write_text("{not json", encoding="utf-8")
    assert cm.load_cached_claude_models() == ([], "")


def test_load_cached_models_normalizes_entries(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(cm, "_cache_path", lambda: tmp_path / "cache.json")
    (tmp_path / "cache.json").write_text(
        json.dumps(
            {
                "fetched_at": "2026-10-09T00:00:00+00:00",
                "models": [
                    {"slug": "opus", "display_name": "Opus"},
                    {"slug": "haiku"},  # display_name falls back to the slug
                    {"display_name": "no slug"},  # dropped
                    "not a dict",  # dropped
                ],
            }
        ),
        encoding="utf-8",
    )
    models, fetched_at = cm.load_cached_claude_models()
    assert fetched_at == "2026-10-09T00:00:00+00:00"
    assert models == [
        {"slug": "opus", "display_name": "Opus"},
        {"slug": "haiku", "display_name": "haiku"},
    ]


# ---- sync orchestration --------------------------------------------------------


@pytest.mark.asyncio
async def test_sync_parses_screen_and_writes_cache(tmp_path, monkeypatch) -> None:
    cache_file = tmp_path / "cache.json"
    monkeypatch.setattr(cm, "_cache_path", lambda: cache_file)
    monkeypatch.setattr(cm, "_capture_model_screen", lambda: SCREEN)

    models, fetched_at = await cm.sync_claude_models()
    assert [m["slug"] for m in models] == ["opus", "opus[1m]", "haiku"]
    assert fetched_at  # an iso timestamp was minted
    payload = json.loads(cache_file.read_text(encoding="utf-8"))
    assert payload["models"] == models
    assert payload["fetched_at"] == fetched_at


@pytest.mark.asyncio
async def test_sync_failure_branches_return_empty_and_leave_cache_untouched(
    tmp_path, monkeypatch
) -> None:
    cache_file = tmp_path / "cache.json"
    cache_file.write_text(
        json.dumps({"fetched_at": "old", "models": [{"slug": "sonnet"}]}), encoding="utf-8"
    )
    monkeypatch.setattr(cm, "_cache_path", lambda: cache_file)

    def _boom() -> str:
        raise OSError("pty unavailable")

    monkeypatch.setattr(cm, "_capture_model_screen", _boom)
    assert await cm.sync_claude_models() == ([], "")
    monkeypatch.setattr(cm, "_capture_model_screen", lambda: None)  # capture gave up
    assert await cm.sync_claude_models() == ([], "")
    monkeypatch.setattr(cm, "_capture_model_screen", lambda: "no picker rows here")
    assert await cm.sync_claude_models() == ([], "")

    # the pre-existing cache was never rewritten or deleted
    assert json.loads(cache_file.read_text(encoding="utf-8")) == {
        "fetched_at": "old",
        "models": [{"slug": "sonnet"}],
    }
