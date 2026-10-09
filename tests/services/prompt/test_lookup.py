"""The prompt-pack reader: a path walk that refuses to lie.

Every caller of :func:`prompt_text` relies on one contract — it hands back
either the non-empty string at the requested path, or exactly the default
it was given. Anything else in the pack (missing keys, empty templates,
mappings where a string was expected) must collapse to that default rather
than leak the pack's shape into a prompt.
"""

from __future__ import annotations

import pytest

from deeptutor.services.prompt.lookup import prompt_text

PACK: dict = {
    "system": {
        "role": "You are a patient tutor.",
        "empty": "",
        "meta": {"author": "ops"},
    },
    "scalars": {"count": 3, "nothing": None, "items": ["a", "b"]},
}


def test_a_nested_string_is_returned_verbatim() -> None:
    assert prompt_text(PACK, ("system", "role")) == "You are a patient tutor."


def test_a_missing_leaf_key_falls_back_to_the_default() -> None:
    assert prompt_text(PACK, ("system", "role", "sub")) == ""


def test_a_missing_intermediate_key_falls_back_to_the_default() -> None:
    assert prompt_text(PACK, ("absent", "role")) == ""


def test_a_missing_root_key_falls_back_to_the_default() -> None:
    assert prompt_text(PACK, ("nope",)) == ""


def test_an_empty_template_is_treated_as_missing() -> None:
    assert prompt_text(PACK, ("system", "empty")) == ""


def test_an_empty_template_yields_the_custom_default() -> None:
    assert prompt_text(PACK, ("system", "empty"), default="fallback") == "fallback"


def test_a_missing_key_yields_the_custom_default() -> None:
    assert prompt_text(PACK, ("system", "ghost"), default="fallback") == "fallback"


def test_a_mapping_at_the_leaf_is_not_a_prompt() -> None:
    assert prompt_text(PACK, ("system", "meta")) == ""


def test_a_non_string_leaf_is_not_a_prompt() -> None:
    assert prompt_text(PACK, ("scalars", "count")) == ""


def test_a_none_leaf_is_not_a_prompt() -> None:
    assert prompt_text(PACK, ("scalars", "nothing")) == ""


def test_a_list_leaf_is_not_a_prompt() -> None:
    assert prompt_text(PACK, ("scalars", "items")) == ""


def test_a_scalar_mid_path_stops_the_walk() -> None:
    assert prompt_text(PACK, ("system", "role", "deeper")) == ""


def test_a_none_mid_path_stops_the_walk() -> None:
    assert prompt_text(PACK, ("scalars", "nothing", "deeper")) == ""


def test_a_list_mid_path_stops_the_walk() -> None:
    assert prompt_text(PACK, ("scalars", "items", "0")) == ""


def test_an_empty_path_on_a_pack_yields_the_default() -> None:
    assert prompt_text(PACK, ()) == ""


@pytest.mark.parametrize(
    ("path", "expected"),
    [
        (("system", "role"), "You are a patient tutor."),
        (("system", "meta", "author"), "ops"),
        (("system", "missing"), ""),
        (("scalars", "count"), ""),
    ],
)
def test_single_and_multi_level_paths_agree_on_the_contract(
    path: tuple[str, ...], expected: str
) -> None:
    assert prompt_text(PACK, path) == expected
