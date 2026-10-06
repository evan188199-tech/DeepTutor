"""Behavior tests for ``StatusI18n`` (``deeptutor/i18n/status_i18n.py``).

The prompt-service dependency is faked — no real ``PromptManager``, config or
service is started. A tiny stand-in answers ``load_prompts`` either from
canned tables or straight from the repository's own status YAML files, so the
enumeration tests walk every ``status:`` section a capability actually feeds
into ``StatusI18n`` and require non-empty copy per key in every shipped
language, plus en/zh key parity. Key lists are never hardcoded, so the yaml
can evolve freely without snapshot churn.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
import yaml

from deeptutor.i18n.status_i18n import StatusI18n

_REPO = Path(__file__).resolve().parents[2]

# (module, agent) pairs mirroring the StatusI18n(...) call sites in the
# capabilities — kept explicit so each pair documents a real consumer.
_STATUS_PACKS: tuple[tuple[str, str], ...] = (
    ("visualize", "visualize"),
    ("question", "deep_question"),
    ("math_animator", "math_animator"),
    ("capabilities", "audio_overview"),
)
_LANGUAGES = ("en", "zh")


def _prompts_dir(module: str) -> Path:
    if module == "capabilities":
        return _REPO / "deeptutor" / "capabilities" / "prompts"
    return _REPO / "deeptutor" / "agents" / module / "prompts"


def _status_table(module: str, agent: str, language: str) -> dict[str, Any] | None:
    path = _prompts_dir(module) / language / f"{agent}.yaml"
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    status = data.get("status") if isinstance(data, dict) else None
    return status if isinstance(status, dict) else None


class _FakePromptManager:
    """In-memory stand-in that records every load_prompts call."""

    def __init__(self, tables: dict[tuple[str, str, str], Any]) -> None:
        self._tables = tables
        self.calls: list[tuple[str, str, str]] = []

    def load_prompts(self, *, module_name: str, agent_name: str, language: str) -> Any:
        self.calls.append((module_name, agent_name, language))
        return self._tables.get((module_name, agent_name, language))


class _YamlPromptManager:
    """Reads the repository's real prompt YAML files — file reads only."""

    def load_prompts(self, *, module_name: str, agent_name: str, language: str) -> Any:
        path = _prompts_dir(module_name) / language / f"{agent_name}.yaml"
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        return data if isinstance(data, dict) else {}


@pytest.fixture
def fake_prompt_service(monkeypatch):
    """Patch the lazily imported ``get_prompt_manager`` dependency."""

    def _install(manager: Any) -> Any:
        monkeypatch.setattr(
            "deeptutor.services.prompt.get_prompt_manager", lambda: manager
        )
        return manager

    return _install


# ---------------------------------------------------------------------------
# Construction and dependency wiring
# ---------------------------------------------------------------------------


def test_constructor_queries_prompt_service_with_module_agent_language(
    fake_prompt_service,
) -> None:
    manager = fake_prompt_service(_FakePromptManager({}))
    StatusI18n("visualize", "zh-CN", module="visualize")
    assert manager.calls == [("visualize", "visualize", "zh-CN")]


def test_prompts_missing_status_section_leaves_empty_table(fake_prompt_service) -> None:
    fake_prompt_service(
        _FakePromptManager({("m", "a", "en"): {"system": "not a status map"}})
    )
    i18n = StatusI18n("a", "en", module="m")
    assert i18n.t("any_key", "default") == "default"


def test_prompts_not_a_dict_leaves_empty_table(fake_prompt_service) -> None:
    fake_prompt_service(_FakePromptManager({("m", "a", "en"): None}))
    i18n = StatusI18n("a", "en", module="m")
    assert i18n.t("any_key", "default") == "default"


def test_status_section_not_a_dict_leaves_empty_table(fake_prompt_service) -> None:
    fake_prompt_service(_FakePromptManager({("m", "a", "en"): {"status": "oops"}}))
    i18n = StatusI18n("a", "en", module="m")
    assert i18n.t("any_key", "default") == "default"


def test_language_selects_the_table_loaded(fake_prompt_service) -> None:
    tables = {
        ("m", "a", "en"): {"status": {"greeting": "Working..."}},
        ("m", "a", "zh"): {"status": {"greeting": "处理中..."}},
    }
    fake_prompt_service(_FakePromptManager(tables))
    assert StatusI18n("a", "en", module="m").t("greeting") == "Working..."
    assert StatusI18n("a", "zh", module="m").t("greeting") == "处理中..."


# ---------------------------------------------------------------------------
# t(): key lookup and fallback behavior
# ---------------------------------------------------------------------------


def test_missing_key_returns_default(fake_prompt_service) -> None:
    fake_prompt_service(
        _FakePromptManager({("m", "a", "en"): {"status": {"known": "Known."}}})
    )
    i18n = StatusI18n("a", "en", module="m")
    assert i18n.t("missing_key", "English fallback") == "English fallback"


def test_missing_key_without_default_returns_empty_string(fake_prompt_service) -> None:
    fake_prompt_service(_FakePromptManager({("m", "a", "en"): {"status": {}}}))
    assert StatusI18n("a", "en", module="m").t("missing_key") == ""


@pytest.mark.parametrize("bad_value", ["", 42, None, ["not", "a", "string"]])
def test_non_string_or_empty_values_fall_back_to_default(
    fake_prompt_service, bad_value: Any
) -> None:
    fake_prompt_service(
        _FakePromptManager({("m", "a", "en"): {"status": {"broken": bad_value}}})
    )
    i18n = StatusI18n("a", "en", module="m")
    assert i18n.t("broken", "safe default") == "safe default"


def test_placeholders_are_formatted_with_kwargs(fake_prompt_service) -> None:
    fake_prompt_service(
        _FakePromptManager(
            {
                ("m", "a", "en"): {
                    "status": {
                        "rendering": "Rendering {mode} with quality={quality}.",
                        "retry": "Retry {attempt}: {error}",
                    }
                }
            }
        )
    )
    i18n = StatusI18n("a", "en", module="m")
    assert (
        i18n.t("rendering", "", mode="fast", quality="high")
        == "Rendering fast with quality=high."
    )
    assert i18n.t("retry", "", attempt=2, error="boom") == "Retry 2: boom"


def test_format_with_unknown_placeholder_returns_unformatted_text(
    fake_prompt_service,
) -> None:
    fake_prompt_service(
        _FakePromptManager({("m", "a", "en"): {"status": {"msg": "Hello {who}!"}}})
    )
    i18n = StatusI18n("a", "en", module="m")
    assert i18n.t("msg", "", other="x") == "Hello {who}!"


def test_format_with_positional_placeholder_returns_unformatted_text(
    fake_prompt_service,
) -> None:
    fake_prompt_service(
        _FakePromptManager({("m", "a", "en"): {"status": {"msg": "Item {0}"}}})
    )
    i18n = StatusI18n("a", "en", module="m")
    assert i18n.t("msg", "", value="x") == "Item {0}"


def test_kwargs_without_placeholders_leave_text_unchanged(fake_prompt_service) -> None:
    fake_prompt_service(
        _FakePromptManager({("m", "a", "en"): {"status": {"msg": "Plain text."}}})
    )
    i18n = StatusI18n("a", "en", module="m")
    assert i18n.t("msg", "", unused="x") == "Plain text."


def test_braces_are_preserved_when_no_kwargs_given(fake_prompt_service) -> None:
    fake_prompt_service(
        _FakePromptManager({("m", "a", "en"): {"status": {"msg": "Hello {who}!"}}})
    )
    assert StatusI18n("a", "en", module="m").t("msg") == "Hello {who}!"


def test_empty_default_is_a_legitimate_result(fake_prompt_service) -> None:
    fake_prompt_service(_FakePromptManager({("m", "a", "en"): {"status": {}}}))
    assert StatusI18n("a", "en", module="m").t("missing", "") == ""


# ---------------------------------------------------------------------------
# Enumeration: real status packs end-to-end through StatusI18n
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("module,agent", list(_STATUS_PACKS))
@pytest.mark.parametrize("language", list(_LANGUAGES))
def test_status_pack_has_usable_status_section(
    module: str, agent: str, language: str
) -> None:
    path = _prompts_dir(module) / language / f"{agent}.yaml"
    assert path.is_file(), f"missing prompt file for {module}/{agent} [{language}]"
    status = _status_table(module, agent, language)
    assert isinstance(status, dict), f"{path} has no usable 'status:' mapping"


@pytest.mark.parametrize("module,agent", list(_STATUS_PACKS))
def test_status_pack_keys_match_across_languages(module: str, agent: str) -> None:
    en = _status_table(module, agent, "en") or {}
    zh = _status_table(module, agent, "zh") or {}
    assert set(en) == set(zh), (
        f"{module}/{agent}: en-only={sorted(set(en) - set(zh))} "
        f"zh-only={sorted(set(zh) - set(en))}"
    )


@pytest.mark.parametrize("module,agent", list(_STATUS_PACKS))
@pytest.mark.parametrize("language", list(_LANGUAGES))
def test_every_status_key_resolves_to_nonempty_copy(
    fake_prompt_service, module: str, agent: str, language: str
) -> None:
    status = _status_table(module, agent, language) or {}
    assert status, f"{module}/{agent} [{language}] has an empty status section"

    fake_prompt_service(_YamlPromptManager())
    i18n = StatusI18n(agent, language, module=module)

    for key, raw in status.items():
        assert isinstance(raw, str) and raw.strip(), (
            f"{module}/{agent} [{language}] status key {key!r} is not non-empty text"
        )
        assert i18n.t(key, "sentinel") == raw, (
            f"{module}/{agent} [{language}] status key {key!r} does not resolve"
        )
        assert i18n.t("__guaranteed_missing__", "sentinel") == "sentinel"
