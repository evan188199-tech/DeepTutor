"""Contract tests for the ask_questions loop capability.

``capabilities/ask_questions/loop.py`` contributes an adaptive questioning
policy to the normal chat loop. The contracts pinned here:

* **Activation is flag-gated and re-read every lookup.** The turn capability
  sets ``ask_questions_mode`` in ``context.metadata``; every hook consults it,
  and the registry re-evaluates membership per lookup — so a turn that ends,
  is cancelled, or drops the flag stops receiving the policy on the next
  round without any explicit teardown.
* **One prompt block, resolved by language.** An active turn contributes
  exactly one ``ask_questions`` block holding the stripped zh/en resource
  prompt; non-zh languages fall back to the English resource. A broken prompt
  resource must fail loudly: the pipeline does not guard ``system_block``, and
  a silently policy-less questioning turn would look healthy while never
  asking.
* **Loop neutrality.** The capability owns no tools, never becomes exclusive,
  mutates no tool kwargs, seeds nothing before the loop, and defines no
  ``on_user_pause`` / ``on_user_resume`` hooks. The ``ask_user`` wait — its
  timeout/cancel handling and the answer backfill on resume — stays on the
  pipeline's default path by design; these tests pin that the capability does
  not drift into overriding it.
* **Turn start.** ``AskQuestionsCapability.run`` flips the activation flag,
  hands the turn's language to the pipeline, and forces ``ask_user`` as the
  first internal round's tool choice; later rounds return to model-directed
  selection.
"""

from __future__ import annotations

from importlib import resources
from typing import Any

import pytest

from deeptutor.capabilities.ask_questions.capability import AskQuestionsCapability
import deeptutor.capabilities.ask_questions.loop as loop_module
from deeptutor.capabilities.ask_questions.loop import AskQuestionsLoopCapability
from deeptutor.capabilities.protocol import PromptBlock
from deeptutor.capabilities.registry import BUILTIN_LOOP_CAPABILITY_SPECS, active_loop_capabilities
from deeptutor.core.context import UnifiedContext

FLAG = "ask_questions_mode"


def _prompt_text(lang: str) -> str:
    return (
        resources.files("deeptutor.capabilities.ask_questions")
        .joinpath("prompts", lang, "system.md")
        .read_text(encoding="utf-8")
        .strip()
    )


def _context(*, flag: Any = None, **kwargs: Any) -> UnifiedContext:
    context = UnifiedContext(**kwargs)
    if flag is not None:
        context.metadata[FLAG] = flag
    return context


# ── Registry identity ───────────────────────────────────────────────────────────


def test_registry_spec_creates_capability_with_matching_name() -> None:
    spec = next(s for s in BUILTIN_LOOP_CAPABILITY_SPECS if s.name == "ask_questions")
    cap = spec.create()
    assert isinstance(cap, AskQuestionsLoopCapability)
    assert cap.name == "ask_questions"
    assert cap.owned_tools == ()


# ── Structural surface: loop neutrality ────────────────────────────────────────


def test_structural_surface_keeps_pipeline_defaults_for_ask_user_lifecycle() -> None:
    cap = AskQuestionsLoopCapability()
    # Reuses the full chat surface; adds nothing, replaces nothing.
    assert cap.owned_tools == ()
    assert getattr(cap, "exclusive_tools", False) is False
    assert getattr(cap, "skip_kb_seed", None) is None
    # No extra pre-pass before the loop's first LLM call.
    assert getattr(cap, "pre_loop", None) is None
    # No per-round finish guard, no tool rebinding.
    assert getattr(cap, "finish_instruction", None) is None
    assert getattr(cap, "rebinding_tools", ()) == ()
    # The ask_user wait (timeout/cancel bookkeeping on pause, answer backfill
    # on resume) stays on the pipeline's default transcript path: no hooks.
    assert getattr(cap, "on_user_pause", None) is None
    assert getattr(cap, "on_user_resume", None) is None


# ── Activation: flag-gated, re-evaluated per lookup ────────────────────────────


@pytest.mark.parametrize(
    ("flag", "expected"),
    [
        (True, True),
        ("true", True),
        (1, True),
        (None, False),
        (False, False),
        ("", False),
        (0, False),
    ],
)
def test_is_active_follows_metadata_flag(flag: Any, expected: bool) -> None:
    context = _context(flag=flag) if flag is not None else UnifiedContext()
    assert AskQuestionsLoopCapability().is_active(context) is expected


def _active_names(context: UnifiedContext) -> set[str]:
    # Registry membership is computed per lookup and instances are recreated,
    # so compare by name rather than object identity.
    return {cap.name for cap in active_loop_capabilities(context)}


def test_active_set_drops_capability_when_flag_cleared() -> None:
    # Registry membership is computed per lookup, so clearing the flag — turn
    # finished, cancelled, or timed out — removes the policy from the very next
    # round, and restoring it brings it back.
    context = _context(flag=True)
    assert "ask_questions" in _active_names(context)

    del context.metadata[FLAG]
    assert "ask_questions" not in _active_names(context)

    context.metadata[FLAG] = True
    assert "ask_questions" in _active_names(context)


# ── system_block: language resolution and failure modes ────────────────────────


def test_system_block_returns_none_when_inactive_without_touching_loader(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def _explode(language: str) -> str:
        raise AssertionError("inactive turns must not load the prompt resource")

    monkeypatch.setattr(loop_module, "_load_system_prompt", _explode)
    assert (
        AskQuestionsLoopCapability().system_block(UnifiedContext(), language="en", prompts={})
        is None
    )


@pytest.mark.parametrize("language", ["zh", "zh-CN", "ZH-TW"])
def test_system_block_resolves_chinese_prompt(language: str) -> None:
    cap = AskQuestionsLoopCapability()
    block = cap.system_block(_context(flag=True), language=language, prompts={})
    assert block == PromptBlock("ask_questions", _prompt_text("zh"))


@pytest.mark.parametrize("language", ["en", "en-US", "fr"])
def test_system_block_falls_back_to_english_prompt(language: str) -> None:
    cap = AskQuestionsLoopCapability()
    block = cap.system_block(_context(flag=True), language=language, prompts={})
    assert block == PromptBlock("ask_questions", _prompt_text("en"))


def test_prompt_resources_reference_ask_user_and_differ_by_language() -> None:
    # The mode only works if both prompt variants instruct the model to open
    # with the ``ask_user`` tool (first-round card) and continue with the
    # user's answers afterwards — and the variants must actually differ, or
    # the language resolution above would be untestable.
    zh, en = _prompt_text("zh"), _prompt_text("en")
    assert zh and en
    assert zh != en
    assert "ask_user" in zh
    assert "ask_user" in en


def test_system_block_propagates_prompt_loader_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # The pipeline does not guard ``system_block``: a missing/broken prompt
    # resource must surface during prompt assembly instead of silently
    # producing a questioning turn without its policy.
    def _broken(language: str) -> str:
        raise FileNotFoundError("prompts/en/system.md")

    monkeypatch.setattr(loop_module, "_load_system_prompt", _broken)
    with pytest.raises(FileNotFoundError):
        AskQuestionsLoopCapability().system_block(_context(flag=True), language="en", prompts={})


# ── Loop neutrality: kwargs pass-through and empty seed ────────────────────────


@pytest.mark.parametrize("tool_name", ["ask_user", "rag", "read_skill"])
def test_augment_kwargs_is_content_preserving_passthrough(tool_name: str) -> None:
    cap = AskQuestionsLoopCapability()
    kwargs: dict[str, Any] = {"query": "photosynthesis", "top_k": 5}
    context = _context(flag=True)
    result = cap.augment_kwargs(tool_name, kwargs, context)
    assert result == kwargs
    # No private server-side kwargs are injected for a capability with no
    # owned tools, and the caller's dict is not mutated behind its back.
    assert kwargs == {"query": "photosynthesis", "top_k": 5}


@pytest.mark.parametrize("flag", [None, True])
def test_pre_loop_seed_is_empty(flag: bool | None) -> None:
    context = _context(flag=flag) if flag is not None else UnifiedContext()
    assert AskQuestionsLoopCapability().pre_loop_seed(context) == ""


# ── Turn start: capability.run wires flag + first-round tool choice ───────────


class _FakePipeline:
    instances: list["_FakePipeline"] = []

    def __init__(self, language: str = "en", *, initial_tool_choice: str | None = None) -> None:
        self.language = language
        self.initial_tool_choice = initial_tool_choice
        self.run_calls: list[tuple[UnifiedContext, Any]] = []
        type(self).instances.append(self)

    async def run(self, context: UnifiedContext, stream: Any) -> None:
        self.run_calls.append((context, stream))


@pytest.mark.asyncio
@pytest.mark.parametrize("language", ["zh-CN", "en"])
async def test_capability_run_sets_flag_and_forces_first_round_ask_user(
    monkeypatch: pytest.MonkeyPatch, language: str
) -> None:
    _FakePipeline.instances.clear()
    monkeypatch.setattr(
        "deeptutor.capabilities.ask_questions.capability.AgenticChatPipeline",
        _FakePipeline,
    )
    context = UnifiedContext(language=language, user_message="help me plan a study path")
    stream = object()

    await AskQuestionsCapability().run(context, stream)

    assert context.metadata[FLAG] is True
    assert len(_FakePipeline.instances) == 1
    pipeline = _FakePipeline.instances[0]
    assert pipeline.language == language
    # The first internal round of the selected turn must open with the
    # question card; later rounds return to model-directed selection.
    assert pipeline.initial_tool_choice == "ask_user"
    assert pipeline.run_calls == [(context, stream)]
