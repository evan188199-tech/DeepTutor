"""A goal's name is a label, not a restatement of the goal."""

from __future__ import annotations

import asyncio

import pytest

from deeptutor.api.routers.mastery_path import _provisional_name
from deeptutor.learning import topic_naming
from deeptutor.learning.topic_naming import (
    MAX_TITLE_CHARS,
    MAX_TITLE_CHARS_LATIN,
    _MAX_GOAL_CHARS,
    _clean,
    _render,
    suggest_topic_name,
)


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("「时间序列神经网络」", "时间序列神经网络"),
        ('  "Transformer 入门"  ', "Transformer 入门"),
        # A trailing full stop is punctuation on a sentence; a name is not one.
        ("Time-series neural networks.", "Time-series neural networks"),
        ("向量空间与线性变换。", "向量空间与线性变换"),
    ],
)
def test_a_model_answer_is_reduced_to_the_name_itself(raw, expected):
    assert _clean(raw) == expected


def test_a_model_that_explained_itself_is_rejected_rather_than_trimmed():
    """Taking the first line would put "Here is a good name:" on the dashboard."""
    assert _clean("Here is a good name:\nRAG systems") == ""
    assert _clean("") == ""
    assert _clean("   ") == ""


def test_latin_titles_are_cut_on_a_word_boundary():
    """A character is not a unit of meaning: clipping 'networks' to 'netwo' is
    worse than losing the word."""
    long_title = "Everything about retrieval augmented generation and evaluation"
    fitted = _clean(long_title)
    assert len(fitted) <= MAX_TITLE_CHARS_LATIN
    assert not fitted.endswith(" ")
    assert long_title.startswith(fitted)
    assert fitted.split()[-1] in long_title.split()


def test_cjk_titles_use_the_narrower_budget():
    fitted = _clean("时" * 60)
    assert len(fitted) == MAX_TITLE_CHARS


@pytest.mark.asyncio
async def test_an_empty_goal_is_not_worth_an_llm_call(monkeypatch):
    def _boom(*_args, **_kwargs):  # pragma: no cover - must never run
        raise AssertionError("no call should be made for an empty goal")

    monkeypatch.setattr(topic_naming, "_render", _boom)
    assert await suggest_topic_name("   ") == ""


@pytest.mark.asyncio
async def test_a_failed_call_returns_empty_so_creation_can_still_proceed(monkeypatch):
    """The caller has a fallback; a goal that cannot be named must still be
    creatable."""

    async def _fail(*_args, **_kwargs):
        raise RuntimeError("provider is out of credits")

    monkeypatch.setattr("deeptutor.services.llm.complete", _fail)
    assert await suggest_topic_name("我想学线性代数", language="zh") == ""


def test_only_punctuation_reduces_to_no_name():
    assert _clean("。。。") == ""
    assert _clean("!!!") == ""
    assert _clean("「」") == ""


def test_a_single_unbroken_word_clips_at_the_budget():
    """Without a word boundary the budget is still absolute."""
    assert _clean("a" * 100) == "a" * MAX_TITLE_CHARS_LATIN


def test_mixed_script_titles_follow_the_dominant_script():
    cjk_heavy = _clean("时间序列神经网络的注意力机制 Deep Learning")
    assert len(cjk_heavy) <= MAX_TITLE_CHARS
    assert cjk_heavy.endswith("Deep")

    latin_goal = "Deep learning for time series forecasting with attention mechanisms 深度"
    latin_heavy = _clean(latin_goal)
    assert len(latin_heavy) <= MAX_TITLE_CHARS_LATIN
    assert latin_heavy.split()[-1] in latin_goal.split()


@pytest.mark.asyncio
async def test_a_successful_answer_becomes_the_name_not_the_goal(monkeypatch):
    async def _answer(**_kwargs):
        return "时间序列神经网络"

    monkeypatch.setattr("deeptutor.services.llm.complete", _answer)
    goal = "我想学习有关时间序列神经网络的一切"
    name = await suggest_topic_name(goal, language="zh")
    assert name == "时间序列神经网络"
    assert name != goal


@pytest.mark.asyncio
async def test_the_call_is_one_short_bounded_request(monkeypatch):
    seen: dict = {}

    async def _answer(**kwargs):
        seen.update(kwargs)
        return "线性代数"

    monkeypatch.setattr("deeptutor.services.llm.complete", _answer)
    name = await suggest_topic_name(
        "我想学线性代数",
        source_labels=["教材：线性代数"],
        language="zh",
    )
    assert name == "线性代数"
    assert seen["temperature"] == 0.3
    assert seen["max_tokens"] == 60
    assert seen["max_retries"] == 0
    assert seen["system_prompt"] == topic_naming._SYSTEM_ZH
    assert "我想学线性代数" in seen["prompt"]
    assert "教材：线性代数" in seen["prompt"]


@pytest.mark.asyncio
async def test_a_slow_provider_does_not_hold_creation_hostage(monkeypatch):
    async def _slow(**_kwargs):
        await asyncio.sleep(0.5)
        return "姗姗来迟"

    monkeypatch.setattr("deeptutor.services.llm.complete", _slow)
    monkeypatch.setattr(topic_naming, "_TIMEOUT_SECONDS", 0.05)
    assert await suggest_topic_name("我想学线性代数", language="zh") == ""


@pytest.mark.asyncio
async def test_the_reader_language_setting_drives_the_prompt_language(monkeypatch):
    seen: dict = {}

    async def _answer(**kwargs):
        seen.update(kwargs)
        return "Linear algebra"

    monkeypatch.setattr("deeptutor.services.llm.complete", _answer)
    monkeypatch.setattr(
        "deeptutor.services.settings.interface_settings.get_response_language",
        lambda default="en": "zh",
    )
    await suggest_topic_name("Everything about linear algebra")
    assert seen["system_prompt"] == topic_naming._SYSTEM_ZH


@pytest.mark.asyncio
async def test_an_unreadable_language_setting_still_names_the_goal(monkeypatch):
    seen: dict = {}

    async def _answer(**kwargs):
        seen.update(kwargs)
        return "Linear algebra"

    monkeypatch.setattr("deeptutor.services.llm.complete", _answer)

    def _boom(default="en"):
        raise RuntimeError("settings unavailable")

    monkeypatch.setattr(
        "deeptutor.services.settings.interface_settings.get_response_language",
        _boom,
    )
    assert await suggest_topic_name("Everything about linear algebra") == "Linear algebra"
    assert seen["system_prompt"] == topic_naming._SYSTEM_EN


def test_materials_are_listed_bounded_in_the_prompt():
    labels = [f"资料{i}" for i in range(8)]
    zh_prompt = _render("时间序列", labels, zh=True)
    assert "学习目标：\n时间序列" in zh_prompt
    assert "\n学习资料：\n" in zh_prompt
    assert "- 资料5" in zh_prompt
    assert "- 资料6" not in zh_prompt

    en_prompt = _render("time series", labels, zh=False)
    assert "Learning goal:\ntime series" in en_prompt
    assert "\nMaterials:\n" in en_prompt
    assert "- 资料7" not in en_prompt


def test_blank_material_labels_show_only_the_goal():
    assert _render("时间序列", ["", "   "], zh=True) == "学习目标：\n时间序列"
    assert _render("time series", [], zh=False) == "Learning goal:\ntime series"


def test_an_overlong_goal_is_clipped_in_the_prompt_not_dropped():
    long_goal = "很长的目标" * 400
    prompt = _render(long_goal, [], zh=True)
    goal_line = prompt.split("\n")[1]
    assert len(goal_line) == _MAX_GOAL_CHARS
    assert long_goal.startswith(goal_line)


@pytest.mark.asyncio
async def test_a_misbehaving_model_cannot_put_one_sentence_in_three_places(monkeypatch):
    """The regression this module exists for: the same sentence used to become
    title, subtitle and sidebar entry at once."""

    goal = "我想学习有关时间序列神经网络的注意力机制与长期预测方法的全部内容。包括基础概念"

    async def _echo(**_kwargs):
        return goal

    monkeypatch.setattr("deeptutor.services.llm.complete", _echo)
    name = await suggest_topic_name(goal, language="zh")
    fallback = _provisional_name(goal)
    assert name != goal
    assert fallback != goal
    assert name != fallback
    assert len(name) <= MAX_TITLE_CHARS
