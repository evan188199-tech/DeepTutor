"""Contract and boundary coverage for pre-execution capability routing."""

from __future__ import annotations

import dataclasses

import pytest

from deeptutor.runtime.capability_routing import (
    CapabilityRoute,
    route_explicit_quiz_request,
)


class TestCapabilityRouteContract:
    def test_as_metadata_exposes_all_fields(self) -> None:
        route = CapabilityRoute(
            requested_capability="chat",
            capability="deep_question",
            confidence=0.96,
            strategy="rule",
            reason="explicit quiz ask",
        )
        assert route.as_metadata() == {
            "requested_capability": "chat",
            "capability": "deep_question",
            "confidence": 0.96,
            "strategy": "rule",
            "reason": "explicit quiz ask",
            "auto_routed": True,
        }

    @pytest.mark.parametrize(
        ("requested", "capability", "expected"),
        [
            ("chat", "deep_question", True),
            ("chat", "chat", False),
            ("deep_question", "deep_question", False),
        ],
    )
    def test_auto_routed_reflects_capability_change(
        self, requested: str, capability: str, expected: bool
    ) -> None:
        route = CapabilityRoute(
            requested_capability=requested,
            capability=capability,
            confidence=1.0,
            strategy="rule",
            reason="any",
        )
        assert route.auto_routed is expected

    def test_route_is_frozen(self) -> None:
        route = CapabilityRoute(
            requested_capability="chat",
            capability="deep_question",
            confidence=0.96,
            strategy="rule",
            reason="any",
        )
        with pytest.raises(dataclasses.FrozenInstanceError):
            route.capability = "chat"  # type: ignore[misc]


class TestExplicitQuizRouteMatching:
    @pytest.mark.parametrize(
        "content",
        [
            "generate quiz question",
            "generate quiz questions",
            "GENERATE QUIZ QUESTIONS",
            "create quiz questions",
            "make quiz questions",
            "write quiz questions",
            "give me quiz questions",
            "produce 5 quiz questions for me",
            "生成测验题",
            "请生成测试题",
            "帮我出10道考试题",
            "创建考试题",
        ],
    )
    def test_generation_requests_route_to_deep_question(self, content: str) -> None:
        route = route_explicit_quiz_request(content, "chat", enabled=True)
        assert route is not None
        assert route.capability == "deep_question"
        assert route.requested_capability == "chat"
        assert route.strategy == "rule"
        assert route.confidence == 0.96
        assert route.reason
        assert route.auto_routed is True

    @pytest.mark.parametrize(
        "content",
        [
            "generate. quiz questions",
            "generate\nquiz questions",
            "generate squiz questions",
            "please quiz me",
        ],
    )
    def test_non_generation_mentions_stay_in_chat(self, content: str) -> None:
        assert route_explicit_quiz_request(content, "chat", enabled=True) is None

    @pytest.mark.parametrize(
        ("content", "expected"),
        [
            ("generate " + "x" * 78 + " quiz questions", True),
            ("generate " + "x" * 81 + " quiz questions", False),
            ("生成" + "章" * 20 + "测验题", True),
            ("生成" + "章" * 21 + "测验题", False),
        ],
    )
    def test_matcher_gap_length_limit(self, content: str, expected: bool) -> None:
        routed = route_explicit_quiz_request(content, "chat", enabled=True) is not None
        assert routed is expected


class TestRouteGates:
    def test_disabled_routing_never_routes(self) -> None:
        assert (
            route_explicit_quiz_request("generate quiz questions", "chat", enabled=False) is None
        )

    @pytest.mark.parametrize(
        "requested",
        ["deep_question", "deep_solve", "mastery_path", "visualize"],
    )
    def test_non_chat_requested_capability_is_never_routed(self, requested: str) -> None:
        assert (
            route_explicit_quiz_request("generate quiz questions", requested, enabled=True) is None
        )

    @pytest.mark.parametrize("requested", [None, ""])
    def test_missing_requested_capability_defaults_to_chat(self, requested: object) -> None:
        route = route_explicit_quiz_request("generate quiz questions", requested, enabled=True)
        assert route is not None
        assert route.requested_capability == "chat"

    @pytest.mark.parametrize("workspace_mode", ["mastery_path", "immersive_reading", "notebook"])
    def test_workspace_turns_are_never_routed(self, workspace_mode: str) -> None:
        assert (
            route_explicit_quiz_request(
                "generate quiz questions", "chat", enabled=True, workspace_mode=workspace_mode
            )
            is None
        )

    @pytest.mark.parametrize("workspace_mode", [None, "", "   "])
    def test_blank_workspace_mode_does_not_block_routing(self, workspace_mode: object) -> None:
        assert (
            route_explicit_quiz_request(
                "generate quiz questions", "chat", enabled=True, workspace_mode=workspace_mode
            )
            is not None
        )

    @pytest.mark.parametrize("content", [None, "", "   "])
    def test_blank_content_is_never_routed(self, content: object) -> None:
        assert route_explicit_quiz_request(content, "chat", enabled=True) is None
