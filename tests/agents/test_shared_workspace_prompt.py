"""Contract tests for the shared workspace prompt assembly.

Covers ``workspace_system_note`` directly: input collection (runtime
workspace, language, allow_export), defaults (missing workspace, default
logical output dir, default export policy), and language/export branching.
"""

from __future__ import annotations

from typing import Any

import pytest

from deeptutor.agents._shared.workspace_prompt import workspace_system_note
from deeptutor.core.context import TurnRuntimeContext, UnifiedContext, WorkspaceRuntimeContext

PHYSICAL_ROOT = "/host/hidden/ws"
LOGICAL_DIR = "outputs/chat/s/t"

ZH_HEADER = "[用户 Workspace]"
EN_HEADER = "[User workspace]"


def _workspace(logical: str = LOGICAL_DIR) -> WorkspaceRuntimeContext:
    return WorkspaceRuntimeContext(
        workspace_id="ws_test",
        root=PHYSICAL_ROOT,
        output_dir=f"{PHYSICAL_ROOT}/{LOGICAL_DIR}",
        logical_output_dir=logical,
    )


def _note(
    language: str,
    *,
    logical: str = LOGICAL_DIR,
    allow_export: bool | None = None,
) -> str:
    context = UnifiedContext(runtime=TurnRuntimeContext(workspace=_workspace(logical)))
    kwargs: dict[str, Any] = {} if allow_export is None else {"allow_export": allow_export}
    return workspace_system_note(context, language=language, **kwargs)


@pytest.mark.parametrize("language", ["en", "zh"])
def test_note_is_empty_without_a_runtime_workspace(language: str) -> None:
    assert workspace_system_note(UnifiedContext(), language=language) == ""


@pytest.mark.parametrize("language", ["en", "zh"])
def test_default_logical_output_dir_is_outputs(language: str) -> None:
    context = UnifiedContext(runtime=TurnRuntimeContext(workspace=_workspace("outputs")))
    note = workspace_system_note(context, language=language)
    assert "`outputs/`" in note
    assert LOGICAL_DIR not in note


@pytest.mark.parametrize(
    ("language", "allow_export", "expected", "absent"),
    [
        (
            "zh",
            False,
            "不要写入 outputs/ 之外的位置。",
            "workspace_export",
        ),
        (
            "zh",
            True,
            "workspace_export 请求一次性授权",
            "不要写入 outputs/ 之外的位置。",
        ),
        (
            "en",
            False,
            "Do not write outside outputs/.",
            "workspace_export",
        ),
        (
            "en",
            True,
            "request one-time authorization with workspace_export",
            "Do not write outside outputs/.",
        ),
    ],
    ids=["zh-default-deny", "zh-allow-once", "en-default-deny", "en-allow-once"],
)
def test_export_guidance_follows_the_allow_export_flag(
    language: str,
    allow_export: bool,
    expected: str,
    absent: str,
) -> None:
    note = _note(language, allow_export=allow_export)
    assert expected in note
    assert absent not in note


@pytest.mark.parametrize("language", ["en", "zh"])
def test_note_names_the_workspace_tool_contract(language: str) -> None:
    note = _note(language)
    for marker in (
        ZH_HEADER if language == "zh" else EN_HEADER,
        "workspace_list",
        "workspace_search",
        "workspace_read",
        "workspace_present",
        "DEEPTUTOR_WORKSPACE_ROOT",
    ):
        assert marker in note


@pytest.mark.parametrize("language", ["en", "zh"])
def test_note_never_leaks_the_physical_root(language: str) -> None:
    note = _note(language)
    assert f"`{LOGICAL_DIR}/`" in note
    assert PHYSICAL_ROOT not in note
    assert "/host/hidden" not in note


@pytest.mark.parametrize(
    ("language", "zh_expected"),
    [
        ("ZH", True),
        ("zh-CN", True),
        ("zh", True),
        ("En", False),
        ("EN-US", False),
        ("", False),
    ],
    ids=["upper-zh", "zh-locale", "plain-zh", "mixed-en", "upper-en", "empty"],
)
def test_language_detection_is_case_insensitive_prefix(
    language: str,
    zh_expected: bool,
) -> None:
    note = _note(language)
    assert (ZH_HEADER in note) is zh_expected
    assert (EN_HEADER in note) is not zh_expected


@pytest.mark.parametrize("language", ["en", "zh"])
def test_deny_and_authorize_guidance_are_exclusive(language: str) -> None:
    denied = _note(language, allow_export=False)
    authorized = _note(language, allow_export=True)
    assert "workspace_export" in authorized
    assert "workspace_export" not in denied


def test_language_is_keyword_only() -> None:
    context = UnifiedContext(runtime=TurnRuntimeContext(workspace=_workspace()))
    with pytest.raises(TypeError):
        workspace_system_note(context, "zh")  # type: ignore[misc]
