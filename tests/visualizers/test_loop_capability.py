from __future__ import annotations

from typing import Any

import pytest

from deeptutor.core.context import UnifiedContext
from deeptutor.visualizers.loop_capability import VisualizationLoopCapability
from deeptutor.visualizers.protocol import (
    REQUESTED_VISUALIZER_KEY,
    VISUALIZATION_RESULT_KEY,
    VISUALIZE_MODE_KEY,
)

CATALOG_PREFIX = "fake-catalog"


class _FakeRegistry:
    def prompt_catalog(self, requested: str = "auto") -> str:
        return f"{CATALOG_PREFIX}:{requested}"


@pytest.fixture
def fake_registry(monkeypatch: pytest.MonkeyPatch) -> _FakeRegistry:
    registry = _FakeRegistry()
    monkeypatch.setattr(
        "deeptutor.visualizers.loop_capability.get_visualizer_registry",
        lambda: registry,
    )
    return registry


def _context(metadata: dict[str, Any] | None = None) -> UnifiedContext:
    return UnifiedContext(
        session_id="s",
        user_message="draw something",
        metadata=metadata or {},
    )


@pytest.mark.parametrize(
    ("metadata", "expected"),
    [
        pytest.param({}, False, id="empty-metadata"),
        pytest.param({VISUALIZE_MODE_KEY: ""}, False, id="empty-mode-string"),
        pytest.param({VISUALIZE_MODE_KEY: False}, False, id="falsy-mode"),
        pytest.param({VISUALIZE_MODE_KEY: "mindmap"}, True, id="mode-enabled"),
    ],
)
def test_is_active_boundary_table(
    fake_registry: _FakeRegistry,
    metadata: dict[str, Any],
    expected: bool,
) -> None:
    assert VisualizationLoopCapability().is_active(_context(metadata)) is expected


@pytest.mark.parametrize(
    ("metadata", "language", "expected_block"),
    [
        pytest.param({}, "en", None, id="empty-metadata-inactive"),
        pytest.param({}, "zh", None, id="empty-metadata-inactive-zh"),
        pytest.param({VISUALIZE_MODE_KEY: True}, "en", "auto", id="mode-only-defaults-auto"),
        pytest.param({VISUALIZE_MODE_KEY: True}, "zh", "auto", id="mode-only-defaults-auto-zh"),
        pytest.param(
            {VISUALIZE_MODE_KEY: True, REQUESTED_VISUALIZER_KEY: "mindmap"},
            "en",
            "mindmap",
            id="mode-and-requested",
        ),
        pytest.param(
            {VISUALIZE_MODE_KEY: True, REQUESTED_VISUALIZER_KEY: ""},
            "en",
            "auto",
            id="empty-requested-falls-back-to-auto",
        ),
    ],
)
def test_system_block_activation_table(
    fake_registry: _FakeRegistry,
    metadata: dict[str, Any],
    language: str,
    expected_block: str | None,
) -> None:
    block = VisualizationLoopCapability().system_block(
        _context(metadata), language=language, prompts={}
    )
    if expected_block is None:
        assert block is None
        return
    assert block is not None
    assert block.name == "visualization_protocol"
    assert block.content.endswith(f"{CATALOG_PREFIX}:{expected_block}")
    assert f"`{expected_block}`" in block.content
    if language == "zh":
        assert "可视化生成任务" in block.content
        assert "visualization generation mode" not in block.content
    else:
        assert "visualization generation mode" in block.content
        assert "可视化生成任务" not in block.content


@pytest.mark.parametrize(
    ("tool_name", "metadata", "expected_requested"),
    [
        pytest.param("submit_visualization", {}, "auto", id="submit-tool-empty-metadata"),
        pytest.param(
            "submit_visualization",
            {REQUESTED_VISUALIZER_KEY: "mindmap"},
            "mindmap",
            id="submit-tool-requested-set",
        ),
        pytest.param(
            "read_source",
            {REQUESTED_VISUALIZER_KEY: "mindmap"},
            None,
            id="other-tool-untouched",
        ),
    ],
)
def test_augment_kwargs_boundary_table(
    fake_registry: _FakeRegistry,
    tool_name: str,
    metadata: dict[str, Any],
    expected_requested: str | None,
) -> None:
    context = _context(metadata)
    kwargs: dict[str, Any] = {"payload": "{}"}
    result = VisualizationLoopCapability().augment_kwargs(tool_name, kwargs, context)
    if expected_requested is None:
        assert result is kwargs
        assert "_visualize_context" not in result
        return
    assert result is not kwargs
    assert kwargs == {"payload": "{}"}
    assert result["_visualize_context"] is context
    assert result["_visualizer_registry"] is fake_registry
    assert result["_requested_visualizer"] == expected_requested


@pytest.mark.parametrize(
    ("metadata", "expected_requested"),
    [
        pytest.param({}, "auto", id="empty-metadata-defaults-auto"),
        pytest.param({REQUESTED_VISUALIZER_KEY: ""}, "auto", id="empty-requested-falls-back"),
        pytest.param(
            {REQUESTED_VISUALIZER_KEY: "number_line"},
            "number_line",
            id="requested-preserved",
        ),
    ],
)
def test_pre_loop_seed_boundary_table(
    fake_registry: _FakeRegistry,
    metadata: dict[str, Any],
    expected_requested: str,
) -> None:
    seed = VisualizationLoopCapability().pre_loop_seed(_context(metadata))
    assert seed == f"[Visualization mode: requested_type={expected_requested}]"


@pytest.mark.parametrize(
    ("metadata", "finish_expected", "override_expected"),
    [
        pytest.param(
            {},
            (
                "No valid visualization has been committed yet. Call "
                "submit_visualization now with a complete payload; if a previous "
                "submission failed, repair the reported validation error."
            ),
            None,
            id="no-result-prompts-retry",
        ),
        pytest.param(
            {VISUALIZATION_RESULT_KEY: "committed"},
            "",
            "",
            id="result-committed-silences-both",
        ),
    ],
)
def test_finish_instruction_and_final_override_result_states_table(
    fake_registry: _FakeRegistry,
    metadata: dict[str, Any],
    finish_expected: str,
    override_expected: str | None,
) -> None:
    capability = VisualizationLoopCapability()
    context = _context(metadata)
    assert capability.finish_instruction(context, "draft answer") == finish_expected
    assert capability.final_text_override(context, "draft answer") == override_expected


@pytest.mark.parametrize(
    "metadata",
    [
        pytest.param({}, id="empty-metadata"),
        pytest.param({VISUALIZE_MODE_KEY: True}, id="mode-only"),
        pytest.param(
            {VISUALIZE_MODE_KEY: True, VISUALIZATION_RESULT_KEY: "committed"},
            id="mode-and-result",
        ),
    ],
)
def test_tool_round_output_policy_always_discards(
    fake_registry: _FakeRegistry,
    metadata: dict[str, Any],
) -> None:
    policy = VisualizationLoopCapability().tool_round_output_policy(
        _context(metadata), "prose", ("submit_visualization",)
    )
    assert policy == "discard"


def test_capability_surface_attributes(fake_registry: _FakeRegistry) -> None:
    capability = VisualizationLoopCapability()
    assert capability.name == "visualization_generation"
    assert capability.owned_tools == ("submit_visualization",)
    assert capability.buffers_visible_output is True
