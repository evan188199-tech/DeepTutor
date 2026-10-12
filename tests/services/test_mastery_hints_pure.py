from __future__ import annotations

from deeptutor.services.mastery_hints import (
    _MAX_HINT_CHARS,
    AskHint,
    _cache_key,
    _Material,
    _render,
    _sanitize,
)


def _material(**overrides) -> _Material:
    base = dict(
        path_name="Fourier Analysis",
        goal="Understand spectral methods",
        module_name="Foundations",
        waypoint="Convolution theorem",
        waypoint_type="concept",
        status="learning",
        transcript=[("user", "Why does convolution in time equal multiplication in frequency?")],
        anchor="kp-1:3",
    )
    base.update(overrides)
    return _Material(**base)


def test_cache_key_joins_positions_with_nul_separators() -> None:
    assert _cache_key("path-1", "kp-9", "12") == "path-1\0kp-9\x0012"
    assert "\0" in _cache_key("", "", "")
    assert len(_cache_key("a", "b", "c").split("\0")) == 3


def test_material_truthiness_follows_waypoint_presence() -> None:
    assert _material()
    assert not _material(waypoint="")


def test_sanitize_strips_fences_quotes_and_markdown_debris() -> None:
    assert _sanitize('```\nWhy does aliasing occur?\n```', "en") == "Why does aliasing occur?"
    assert _sanitize('"Why does aliasing occur?"', "en") == "Why does aliasing occur?"
    assert _sanitize("“为什么会出现混叠？”", "zh") == "为什么会出现混叠？"
    assert _sanitize("「为什么会出现混叠？」", "zh") == "为什么会出现混叠？"
    assert _sanitize("- Why does aliasing occur?", "en") == "Why does aliasing occur?"
    assert _sanitize("* Why does aliasing occur?", "en") == "Why does aliasing occur?"
    assert _sanitize("# Why does aliasing occur?", "en") == "Why does aliasing occur?"
    assert _sanitize("•  Why   does aliasing occur?  ", "en") == "Why does aliasing occur?"


def test_sanitize_collapses_multiline_candidates_into_one_scannable_line() -> None:
    raw = "Aliasing happens when\nthe sampling theorem\nis violated.\nWhat causes aliasing?"
    assert _sanitize(raw, "en") == (
        "Aliasing happens when the sampling theorem is violated. What causes aliasing?"
    )
    assert _sanitize("Because the router\npicks by intent.", "en") == ""


def test_sanitize_rejects_non_questions_and_empty_input() -> None:
    assert _sanitize("", "en") == ""
    assert _sanitize(None, "en") == ""
    assert _sanitize("   \n\t  ", "en") == ""
    assert _sanitize("Convolution multiplies spectra.", "en") == ""
    assert _sanitize("卷积把时域和频域联系起来。", "zh") == ""


def test_sanitize_accepts_fullwidth_question_mark_for_chinese() -> None:
    assert _sanitize("什么是混叠？", "zh") == "什么是混叠？"


def test_sanitize_enforces_per_language_length_caps() -> None:
    zh_cap = _MAX_HINT_CHARS["zh"]
    en_cap = _MAX_HINT_CHARS["en"]
    at_zh_cap = "字" * (zh_cap - 1) + "？"
    over_zh_cap = "字" * zh_cap + "？"
    assert len(at_zh_cap) == zh_cap
    assert _sanitize(at_zh_cap, "zh") == at_zh_cap
    assert _sanitize(over_zh_cap, "zh") == ""

    at_en_cap = "w" * (en_cap - 1) + "?"
    over_en_cap = "w" * en_cap + "?"
    assert len(at_en_cap) == en_cap
    assert _sanitize(at_en_cap, "en") == at_en_cap
    assert _sanitize(over_en_cap, "en") == ""


def test_sanitize_uses_chinese_cap_when_language_is_chinese() -> None:
    question = "字" * 50 + "？"
    assert _sanitize(question, "zh") == ""
    assert _sanitize(question, "en") == question


def test_render_english_prompt_contains_position_and_transcript_sections() -> None:
    prompt = _render(_material(), zh=False)
    assert "# Topic\nFourier Analysis" in prompt
    assert "# Goal\nUnderstand spectral methods" in prompt
    assert "# Current waypoint\nConvolution theorem (module: Foundations)" in prompt
    assert "\nType: concept" in prompt
    assert "\nStatus: learning" in prompt
    assert "[Learner] Why does convolution in time equal multiplication in frequency?" in prompt
    assert prompt.endswith("Write that one question.")


def test_render_chinese_prompt_translates_every_section() -> None:
    prompt = _render(_material(), zh=True)
    assert "# 学习主题\nFourier Analysis" in prompt
    assert "# 学习目标\nUnderstand spectral methods" in prompt
    assert "# 当前知识点\nConvolution theorem（所属模块：Foundations）" in prompt
    assert "\n类型：concept" in prompt
    assert "\n掌握状态：learning" in prompt
    assert "[学习者] Why does convolution in time equal multiplication in frequency?" in prompt
    assert prompt.endswith("请写出那一个问题。")


def test_render_uses_tutor_speaker_label_for_assistant_turns() -> None:
    material = _material(
        transcript=[
            ("user", "first question"),
            ("assistant", "first answer"),
            ("system", "ignored role passes through"),
        ]
    )
    prompt = _render(material, zh=False)
    assert "[Learner] first question" in prompt
    assert "[Tutor] first answer" in prompt
    assert "[system] ignored role passes through" in prompt


def test_render_without_transcript_signals_an_opening_question() -> None:
    en = _render(_material(transcript=[]), zh=False)
    zh = _render(_material(transcript=[]), zh=True)
    assert "(Nothing yet — this is their opening question.)" in en
    assert "（还没开始，这是他要问的第一个问题。）" in zh


def test_render_omits_empty_optional_fields() -> None:
    material = _material(goal="", module_name="", waypoint_type="", status="")
    prompt = _render(material, zh=False)
    assert "# Goal" not in prompt
    assert "(module:" not in prompt
    assert "Type:" not in prompt
    assert "Status:" not in prompt
    assert "# Current waypoint\nConvolution theorem\n" in prompt


def test_ask_hint_to_dict_round_trips_every_field() -> None:
    hint = AskHint(hint="What breaks first?", knowledge_point_id="kp-3", generated_at=12.5)
    assert hint.to_dict() == {
        "hint": "What breaks first?",
        "knowledge_point_id": "kp-3",
        "generated_at": 12.5,
    }
