"""Table-driven coverage for the skill taxonomy tables and lookup helpers.

Covers table well-formedness, value-frozenset consistency, track/domain
validation, label lookup with locale switching, unknown-entry degradation,
and empty-table branches.
"""

from __future__ import annotations

import pytest

from deeptutor.services.skill import taxonomy
from deeptutor.services.skill.taxonomy import DomainNode, Option

FACET_TABLES = [
    ("TRACK_OPTIONS", "TRACK_VALUES"),
    ("LANGUAGE_OPTIONS", "LANGUAGE_VALUES"),
    ("STAGE_OPTIONS", "STAGE_VALUES"),
    ("FORM_OPTIONS", "FORM_VALUES"),
    ("AUDIENCE_OPTIONS", "AUDIENCE_VALUES"),
]


@pytest.mark.parametrize(["options_attr", "values_attr"], FACET_TABLES)
def test_facet_table_wellformed(options_attr: str, values_attr: str) -> None:
    options: tuple[Option, ...] = getattr(taxonomy, options_attr)
    values = getattr(taxonomy, values_attr)
    assert options
    assert values == frozenset(o.value for o in options)
    assert len(values) == len(options)
    for o in options:
        assert o.value
        assert o.value == o.value.lower()
        assert o.zh and o.en


@pytest.mark.parametrize(
    ["locale", "expected"],
    [(None, "中文"), ("zh", "中文"), ("en", "Chinese"), ("fr", "中文")],
)
def test_option_label_locale(locale: str | None, expected: str) -> None:
    o = Option("zh", "中文", "Chinese")
    if locale is None:
        assert o.label() == expected
    else:
        assert o.label(locale) == expected


@pytest.mark.parametrize(
    ["locale", "expected"],
    [(None, "通用素养"), ("zh", "通用素养"), ("en", "General"), ("fr", "通用素养")],
)
def test_domain_node_label_locale(locale: str | None, expected: str) -> None:
    node = DomainNode("general", "通用素养", "General")
    if locale is None:
        assert node.label() == expected
    else:
        assert node.label(locale) == expected


@pytest.mark.parametrize(
    ["value", "expected"],
    [
        ("academics", True),
        ("companions", True),
        ("skills-interests", True),
        ("educators", True),
        ("nope", False),
        ("Academics", False),
        (" academics", False),
        ("academics ", False),
        ("", False),
    ],
)
def test_is_valid_track_table(value: str, expected: bool) -> None:
    assert taxonomy.is_valid_track(value) is expected


@pytest.mark.parametrize("option", taxonomy.TRACK_OPTIONS, ids=lambda o: o.value)
def test_track_label_matches_option_labels(option: Option) -> None:
    assert taxonomy.track_label(option.value) == option.zh
    assert taxonomy.track_label(option.value, "zh") == option.zh
    assert taxonomy.track_label(option.value, "en") == option.en


@pytest.mark.parametrize(
    ["value", "locale", "expected"],
    [
        ("academics", "zh", "学业辅导"),
        ("academics", "en", "Academics"),
        ("educators", "zh", "教育者工具"),
        ("educators", "en", "For Educators"),
        ("nope", "zh", "nope"),
        ("nope", "en", "nope"),
        ("", "zh", ""),
    ],
)
def test_track_label_table(value: str, locale: str, expected: str) -> None:
    assert taxonomy.track_label(value, locale) == expected


@pytest.mark.parametrize("node", taxonomy.DOMAIN_TREE, ids=lambda n: n.value)
def test_domain_labels_match_tree(node: DomainNode) -> None:
    assert taxonomy.domain_label(node.value) == node.zh
    assert taxonomy.domain_label(node.value, "en") == node.en
    for child in node.children:
        assert taxonomy.domain_label(child.value) == child.zh
        assert taxonomy.domain_label(child.value, "en") == child.en


@pytest.mark.parametrize(
    ["value", "locale", "expected"],
    [
        ("arts", "zh", "艺术与创意"),
        ("arts", "en", "Arts & Creativity"),
        ("arts.instruments", "zh", "器乐"),
        ("arts.instruments", "en", "Instruments"),
        ("math.calculus", "zh", "微积分"),
        ("math.calculus", "en", "Calculus"),
        ("nope", "zh", "nope"),
        ("nope.child", "en", "nope.child"),
        ("arts.nonexistent", "zh", "arts.nonexistent"),
        ("", "en", ""),
    ],
)
def test_domain_label_table(value: str, locale: str, expected: str) -> None:
    assert taxonomy.domain_label(value, locale) == expected


def test_domain_tree_structure_invariants() -> None:
    roots = [node.value for node in taxonomy.DOMAIN_TREE]
    assert len(roots) == len(set(roots))
    all_children: list[str] = []
    for node in taxonomy.DOMAIN_TREE:
        assert node.children
        child_values = [child.value for child in node.children]
        assert len(child_values) == len(set(child_values))
        for child_value in child_values:
            assert child_value.startswith(f"{node.value}.")
        all_children.extend(child_values)
    assert taxonomy.DOMAIN_VALUES == frozenset(roots + all_children)


def test_domain_node_without_children() -> None:
    leaf = DomainNode("misc", "杂项", "Misc")
    assert leaf.children == ()
    assert leaf.label() == "杂项"
    assert leaf.label("en") == "Misc"


def test_track_lookup_degrades_on_empty_tables(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(taxonomy, "TRACK_OPTIONS", ())
    monkeypatch.setattr(taxonomy, "TRACK_VALUES", frozenset())
    assert taxonomy.track_label("academics") == "academics"
    assert taxonomy.track_label("academics", "en") == "academics"
    assert taxonomy.is_valid_track("academics") is False


def test_domain_label_degrades_on_empty_tree(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(taxonomy, "DOMAIN_TREE", ())
    assert taxonomy.domain_label("arts") == "arts"
    assert taxonomy.domain_label("arts.instruments", "en") == "arts.instruments"
