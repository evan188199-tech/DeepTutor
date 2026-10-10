"""Contract tests for ``VisionSolverAgent.process`` — the orchestration layer
around a mocked LLM.

``test_vision_solver_agent.py`` covers the ``_extract_json`` parser shapes and
the ``verbose=`` kwarg regression; this file covers what that leaves open:

* the parse contract of a mocked LLM reply as seen through ``process()`` —
  including ``_coerce_commands`` normalization and the gated repair pass;
* request parameter validation & passthrough — the no-image short-circuit,
  ``{{ question_text }}`` substitution, the multimodal message shape,
  temperature and model routing;
* failure paths — malformed replies on both passes, provider exceptions and
  timeouts propagating instead of being swallowed, and the missing-prompt-file
  degradation.

Every test is fully mocked and offline; no network is touched.
"""

from __future__ import annotations

import json
from typing import Any

import pytest

import deeptutor.agents.vision_solver.vision_solver_agent as vision_solver_module
from deeptutor.agents.vision_solver.vision_solver_agent import (
    VisionSolverAgent,
    _coerce_commands,
)

# Deterministic prompt with the one placeholder the agent substitutes.
PROMPT_TEMPLATE = "Analyze the figure.\nQuestion: {{ question_text }}\nReturn JSON."

_VALID_REPLY = json.dumps({"commands": [{"command": "A=(0,0)", "description": ""}]})


def _make_agent(
    monkeypatch: pytest.MonkeyPatch,
    *,
    prompt: str = PROMPT_TEMPLATE,
    model: str = "text-model",
    vision_model: str | None = "vl-model",
) -> VisionSolverAgent:
    """A real ``VisionSolverAgent`` with its config dependencies stubbed.

    ``get_agent_params`` is patched so ``BaseAgent.__init__`` never looks for
    the user's ``agents.yaml``; the LLM config comes from the suite-wide
    autouse isolation fixture, so construction never touches the network.
    """
    monkeypatch.setattr(
        "deeptutor.agents.base_agent.get_agent_params",
        lambda _module_name: {},
    )
    agent = VisionSolverAgent(
        api_key="sk-test",
        base_url="https://api.example.invalid/v1",
        model=model,
        vision_model=vision_model,
    )
    agent._prompt = prompt
    return agent


def _install_stream(
    agent: VisionSolverAgent,
    replies: list[str],
    error: Exception | None = None,
) -> list[dict[str, Any]]:
    """Replace ``stream_llm`` with a fake that records kwargs and replays.

    Each reply is streamed in two chunks so chunk accumulation is exercised.
    When ``error`` is set, iterating the stream raises it instead of yielding.
    Returns the list of captured call kwargs, one entry per call.
    """
    calls: list[dict[str, Any]] = []
    queue = list(replies)

    def fake_stream_llm(**kwargs: Any):
        calls.append(kwargs)

        async def _gen():
            if error is not None:
                raise error
            reply = queue.pop(0) if queue else ""
            half = len(reply) // 2
            yield reply[:half]
            yield reply[half:]

        return _gen()

    agent.stream_llm = fake_stream_llm  # type: ignore[method-assign]
    return calls


def _prompt_of(call: dict[str, Any]) -> str:
    """The text part of the multimodal message a captured call sent."""
    return call["messages"][0]["content"][0]["text"]


# ---------------------------------------------------------------------------
# Parse contract through process() — what a mocked LLM reply must look like
# ---------------------------------------------------------------------------


class TestProcessParseContract:
    @pytest.mark.asyncio
    async def test_plain_json_reply_becomes_normalized_commands(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        agent = _make_agent(monkeypatch)
        calls = _install_stream(
            agent,
            [
                json.dumps(
                    {
                        "commands": [{"command": "  A = (1, 2)  ", "description": "point A"}],
                        "constraints": ["AB is a segment"],
                        "image_is_reference": True,
                    }
                )
            ],
        )

        result = await agent.process("q", "img", session_id="s1")

        assert result["has_image"] is True
        assert result["final_ggb_commands"] == [{"command": "A = (1, 2)", "description": "point A"}]
        assert result["analysis_output"]["constraints"] == ["AB is a segment"]
        assert result["image_is_reference"] is True
        # A good first pass never pays for the repair pass.
        assert len(calls) == 1

    @pytest.mark.asyncio
    async def test_fenced_reply_with_mixed_command_shapes(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Fenced JSON is parsed and the commands list degrades gracefully:
        bare strings are kept, junk entries are dropped."""
        agent = _make_agent(monkeypatch)
        reply = (
            "```json\n"
            + json.dumps(
                {
                    "commands": [
                        {"command": "Polygon(A, B, C)", "description": "triangle"},
                        "f(x) = x^2",
                        {"description": "no command field"},
                        {"command": "   "},
                        "",
                        None,
                    ]
                }
            )
            + "\n```"
        )
        _install_stream(agent, [reply])

        result = await agent.process("q", "img")

        assert result["final_ggb_commands"] == [
            {"command": "Polygon(A, B, C)", "description": "triangle"},
            {"command": "f(x) = x^2", "description": ""},
        ]

    @pytest.mark.asyncio
    async def test_missing_commands_field_triggers_repair(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A reply that parses fine but has no ``commands`` key counts as a
        failed first pass and gets exactly one repair attempt."""
        agent = _make_agent(monkeypatch)
        calls = _install_stream(
            agent,
            [
                json.dumps({"constraints": ["no commands key"]}),
                json.dumps({"commands": [{"command": "B = (0, 1)"}]}),
            ],
        )

        result = await agent.process("q", "img")

        assert len(calls) == 2
        assert result["final_ggb_commands"] == [{"command": "B = (0, 1)", "description": ""}]

    @pytest.mark.asyncio
    async def test_non_dict_reply_triggers_repair(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """JSON that parses to a list is not an analysis dict — the agent must
        treat it as a parse failure, not crash on ``.get``."""
        agent = _make_agent(monkeypatch)
        calls = _install_stream(
            agent,
            ['["not", "an", "object"]', json.dumps({"commands": [{"command": "C"}]})],
        )

        result = await agent.process("q", "img")

        assert len(calls) == 2
        assert [c["command"] for c in result["final_ggb_commands"]] == ["C"]

    @pytest.mark.asyncio
    async def test_both_passes_malformed_yield_empty_commands(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Malformed output on both passes still returns the has-image shape,
        with empty commands and no exception — exactly one repair, no more."""
        agent = _make_agent(monkeypatch)
        calls = _install_stream(agent, ["totally not json", "still not json"])

        result = await agent.process("q", "img")

        assert result["has_image"] is True
        assert result["final_ggb_commands"] == []
        assert result["analysis_output"] == {}
        assert result["image_is_reference"] is False
        assert len(calls) == 2

    @pytest.mark.asyncio
    async def test_image_is_reference_absent_defaults_false(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        agent = _make_agent(monkeypatch)
        _install_stream(agent, [json.dumps({"commands": [{"command": "A=(0,0)"}]})])

        result = await agent.process("q", "img")

        assert result["image_is_reference"] is False


# ---------------------------------------------------------------------------
# Request parameter validation & passthrough
# ---------------------------------------------------------------------------


class TestRequestValidationAndPassthrough:
    @pytest.mark.asyncio
    @pytest.mark.parametrize("empty_image", [None, ""])
    async def test_no_image_short_circuits_before_any_llm_call(
        self, monkeypatch: pytest.MonkeyPatch, empty_image: str | None
    ) -> None:
        agent = _make_agent(monkeypatch)
        calls = _install_stream(agent, [_VALID_REPLY])

        result = await agent.process("q", empty_image)

        assert result == {"has_image": False, "final_ggb_commands": []}
        assert calls == []

    @pytest.mark.asyncio
    async def test_question_text_is_substituted_into_prompt(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        agent = _make_agent(monkeypatch)
        calls = _install_stream(agent, [_VALID_REPLY])

        await agent.process("Find the area of triangle ABC", "img")

        prompt = _prompt_of(calls[0])
        assert "Find the area of triangle ABC" in prompt
        assert "{{ question_text }}" not in prompt

    @pytest.mark.asyncio
    async def test_empty_question_leaves_no_placeholder(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        agent = _make_agent(monkeypatch)
        calls = _install_stream(agent, [_VALID_REPLY])

        await agent.process("", "img")

        prompt = _prompt_of(calls[0])
        assert "{{ question_text }}" not in prompt
        assert "Question: \n" in prompt

    @pytest.mark.asyncio
    async def test_multimodal_message_shape_temperature_and_model(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        agent = _make_agent(monkeypatch)  # vision_model="vl-model", model="text-model"
        calls = _install_stream(agent, [_VALID_REPLY])
        image = "data:image/png;base64,QQ=="

        await agent.process("q", image)

        call = calls[0]
        assert call["model"] == "vl-model"  # the vision model serves image input
        assert call["temperature"] == 0.3  # documented default
        assert call["user_prompt"] == ""
        assert call["system_prompt"] == ""
        message = call["messages"][0]
        assert message["role"] == "user"
        text_part, image_part = message["content"]
        assert text_part == {
            "type": "text",
            "text": PROMPT_TEMPLATE.replace("{{ question_text }}", "q"),
        }
        assert image_part == {"type": "image_url", "image_url": {"url": image}}

    @pytest.mark.asyncio
    async def test_vision_model_falls_back_to_model(self, monkeypatch: pytest.MonkeyPatch) -> None:
        agent = _make_agent(monkeypatch, vision_model=None)
        calls = _install_stream(agent, [_VALID_REPLY])

        await agent.process("q", "img")

        assert calls[0]["model"] == "text-model"

    @pytest.mark.asyncio
    async def test_repair_pass_appends_repair_section(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        agent = _make_agent(monkeypatch)
        calls = _install_stream(
            agent, ['{"commands": []}', json.dumps({"commands": [{"command": "R=(1,1)"}]})]
        )

        result = await agent.process("q", "img")

        assert len(calls) == 2
        first, second = _prompt_of(calls[0]), _prompt_of(calls[1])
        assert "修复" not in first
        assert "## 修复" in second
        assert second.startswith(first)  # the repair extends the original prompt
        assert (
            calls[1]["messages"][0]["content"][1]["image_url"]["url"] == "img"
        )  # the image is forwarded on the repair pass too
        assert [c["command"] for c in result["final_ggb_commands"]] == ["R=(1,1)"]


# ---------------------------------------------------------------------------
# Failure paths — provider errors and timeouts surface, never get swallowed
# ---------------------------------------------------------------------------


class TestFailurePaths:
    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "failure",
        [
            TimeoutError("vision call timed out"),
            RuntimeError("provider connection reset"),
        ],
    )
    async def test_stream_failure_propagates_out_of_process(
        self, monkeypatch: pytest.MonkeyPatch, failure: Exception
    ) -> None:
        agent = _make_agent(monkeypatch)
        calls = _install_stream(agent, [], error=failure)

        with pytest.raises(type(failure)):
            await agent.process("q", "img")

        assert len(calls) == 1  # the failure surfaces; there is no silent retry


class TestCoerceCommandsContract:
    @pytest.mark.parametrize(
        "raw, expected",
        [
            (None, []),
            ("A = (1, 2)", []),  # a bare string is not a list
            ({"command": "A"}, []),  # a bare dict is not a list
            ([], []),
            ([None, 42, ""], []),  # non-dict non-str junk is dropped
            ([{"description": "no command"}], []),
            ([{"command": "   "}], []),  # whitespace-only commands are dropped
            (
                [{"command": "  A = (0, 0) ", "description": None}],
                [{"command": "A = (0, 0)", "description": ""}],
            ),
        ],
    )
    def test_coercion_table(self, raw: Any, expected: list[dict[str, Any]]) -> None:
        assert _coerce_commands(raw) == expected


# ---------------------------------------------------------------------------
# Output formatting contract — what the frontend-rendered block looks like
# ---------------------------------------------------------------------------


class TestFormatGgbBlock:
    @staticmethod
    def _format_only_agent() -> VisionSolverAgent:
        # ``format_ggb_block`` reads no instance state, so init can be skipped.
        return VisionSolverAgent.__new__(VisionSolverAgent)

    def test_empty_commands_render_nothing(self) -> None:
        agent = self._format_only_agent()
        assert agent.format_ggb_block([]) == ""
        assert agent.format_ggb_block([{"description": "no command"}]) == ""

    def test_block_framing_and_defaults(self) -> None:
        agent = self._format_only_agent()
        block = agent.format_ggb_block([{"command": "A = (1, 2)", "description": ""}])
        assert block == "```ggbscript[main;题目图形]\nA = (1, 2)\n```"

    def test_custom_page_and_title(self) -> None:
        agent = self._format_only_agent()
        block = agent.format_ggb_block(
            [{"command": "f(x)=x^2", "description": ""}], page_id="p1", title="图 1"
        )
        assert block.startswith("```ggbscript[p1;图 1]\n")
        assert block.endswith("\nf(x)=x^2\n```")

    def test_mixed_entries_are_flattened(self) -> None:
        agent = self._format_only_agent()
        block = agent.format_ggb_block(
            [
                {"command": "A=(0,0)", "description": "origin"},
                "B=(1,1)",
                {"nope": 1},
                None,
                "",
            ]
        )
        assert block == "```ggbscript[main;题目图形]\nA=(0,0)\nB=(1,1)\n```"


# ---------------------------------------------------------------------------
# Construction contract — model fallback and prompt-file degradation
# ---------------------------------------------------------------------------


class TestInitContract:
    def test_vision_model_defaults_to_model(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr("deeptutor.agents.base_agent.get_agent_params", lambda _m: {})
        agent = VisionSolverAgent(api_key="k", base_url="u", model="m-1")
        assert agent.vision_model == "m-1"

    def test_explicit_vision_model_is_kept(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr("deeptutor.agents.base_agent.get_agent_params", lambda _m: {})
        agent = VisionSolverAgent(api_key="k", base_url="u", model="m-1", vision_model="vl-1")
        assert agent.vision_model == "vl-1"

    def test_missing_prompt_file_degrades_to_empty_prompt(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A missing bundled prompt must not break construction — the agent
        degrades to an empty prompt (and a warning) instead of raising."""
        monkeypatch.setattr("deeptutor.agents.base_agent.get_agent_params", lambda _m: {})

        class _MissingPath:
            def __truediv__(self, _other: object) -> "_MissingPath":
                return self

            @property
            def parent(self) -> "_MissingPath":
                return self

            def exists(self) -> bool:
                return False

            def read_text(self, encoding: str | None = None) -> str:
                raise AssertionError("must not read a missing prompt file")

        monkeypatch.setattr(vision_solver_module, "Path", lambda _file: _MissingPath())

        agent = VisionSolverAgent(api_key="k", base_url="u", model="m-1")

        assert agent._prompt == ""

    @pytest.mark.asyncio
    async def test_process_with_empty_prompt_still_parses(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Degraded-prompt construction still completes a normal analysis."""
        monkeypatch.setattr("deeptutor.agents.base_agent.get_agent_params", lambda _m: {})
        agent = VisionSolverAgent(api_key="k", base_url="u", model="m-1")
        agent._prompt = ""
        calls = _install_stream(agent, [_VALID_REPLY])

        result = await agent.process("question without prompt", "img")

        assert _prompt_of(calls[0]) == ""
        assert result["final_ggb_commands"] == [{"command": "A=(0,0)", "description": ""}]
