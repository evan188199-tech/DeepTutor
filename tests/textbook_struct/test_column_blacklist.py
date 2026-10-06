from __future__ import annotations

import pytest

from deeptutor.textbook_struct.column_blacklist import COLUMN_BLACKLIST

CLOSED_VOCABULARY = (
    # civics / politics
    "探究与分享",
    "相关链接",
    "专家点评",
    "名词点击",
    "观点一",
    "观点二",
    "观点三",
    # Chinese / English
    "学习提示",
    "单元导语",
    "思考与探究",
    # math / physics / chemistry / biology
    "思考",
    "探究",
    "实验",
    "练习",
    "习题",
    "复习与巩固",
    "本章小结",
    "信息技术应用",
    "阅读与思考",
    "观察与思考",
    # geography / history
    "问题研究",
    "自学窗",
    "活动",
    "案例",
    "知识窗",
)


def test_vocabulary_matches_the_closed_documented_list() -> None:
    assert isinstance(COLUMN_BLACKLIST, frozenset)
    assert COLUMN_BLACKLIST == frozenset(CLOSED_VOCABULARY)


def test_all_entries_are_clean_closed_vocabulary_names() -> None:
    for name in COLUMN_BLACKLIST:
        assert isinstance(name, str)
        assert name
        assert name == name.strip()
        assert not any(ch.isspace() for ch in name)


@pytest.mark.parametrize("name", CLOSED_VOCABULARY)
def test_activity_columns_are_blocked(name: str) -> None:
    assert name in COLUMN_BLACKLIST


@pytest.mark.parametrize(
    ("candidate", "expected"),
    [
        ("思考", True),
        ("思考与探究", True),
        ("活动", True),
        ("案例", True),
        ("本章小结", True),
        ("知识窗", True),
        ("拓展思考", False),
        ("思考与讨论", False),
        ("活动与讨论", False),
        ("探究与分享会", False),
        ("本章总结", False),
        ("案例分析", False),
        ("思考 ", False),
        (" 思考", False),
    ],
)
def test_membership_requires_an_exact_vocabulary_match(candidate: str, expected: bool) -> None:
    assert (candidate in COLUMN_BLACKLIST) is expected
