"""Column blacklist (layer 0): exact closed vocabulary of feature-column names.

MinerU classifies recurring textbook activity/column names as ``title``
blocks, but they are never chapter headings. The set is closed on purpose —
no fuzzy matching, so near-miss variants must stay outside it.
"""

from __future__ import annotations

from deeptutor.textbook_struct.column_blacklist import COLUMN_BLACKLIST

# Table-driven: every documented column name is a member of the closed set.
BLACKLISTED_NAMES = [
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
]

# Near-miss variants: exact matching only, none of these may be swallowed.
NON_BLACKLISTED_NAMES = [
    "思考探究",  # two names concatenated
    "探究与分享二",  # suffixed
    "拓展探究",  # different prefix
    "综合探究",  # exploration section, not a column
    "课后活动",  # prefixed
    "活动一",  # numbered variant
    "小练习",  # prefixed
    "知识窗格",  # suffixed
    "",  # empty text never matches a closed entry
]


def test_blacklisted_column_names_are_members() -> None:
    for name in BLACKLISTED_NAMES:
        assert name in COLUMN_BLACKLIST, name


def test_lookalike_variants_stay_outside() -> None:
    for name in NON_BLACKLISTED_NAMES:
        assert name not in COLUMN_BLACKLIST, name


def test_blacklist_is_frozen_closed_set() -> None:
    assert isinstance(COLUMN_BLACKLIST, frozenset)
