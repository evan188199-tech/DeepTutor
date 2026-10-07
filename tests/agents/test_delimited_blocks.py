"""Regression tests for delimited-block scanning helpers.

The helpers replace lazy regexes (`````(?:json)?\\s*([\\s\\S]*?)\\s*``` ```` and
``<think>...*</think>`` variants) whose match also succeeds with a missing
closing delimiter scanned from every opening one. These tests pin both
contracts: equivalence with the regexes on well-formed input, and
linear-cost fail-fast on input whose closing delimiter never arrives.
"""

from __future__ import annotations

import re
import time

import pytest

from deeptutor.agents._shared.delimited_blocks import (
    iter_fenced_blocks,
    remove_think_blocks,
    strip_leading_think_blocks,
)

_FENCED_PATTERN = re.compile(r"```(?:json)?\s*([\s\S]*?)\s*```")


def _strip_leading_reference(text: str) -> str:
    while match := re.match(r"<think\b[^>]*>.*?</think>\s*", text, re.DOTALL | re.IGNORECASE):
        text = text[match.end() :]
    return text


@pytest.mark.parametrize(
    "text",
    [
        "",
        "no fences at all",
        "```json\n{}\n```",
        '```\n{"a": 1}\n```',
        "```JSON\n{}\n```",
        "```json5\n{}\n```",
        "``` json\n{}\n```",
        "```json```",
        "``````",
        "```````",
        "```\n```json\ninner\n```",
        "preface ```json\n{}\n``` epilogue",
        "```json\n{}\n``` tail ```\n[]\n```",
        "```json\n{}\n``` unclosed ```json\n[1, 2",
        "```json\nunclosed only",
        "text with ``` mid\n``` and ```x\ny``` end",
        "```\ncontent with ``` inside\n```",
        '  \n```json\t\n {"k": "v"}  \n\n```  ',
    ],
    ids=[
        "empty",
        "no-fence",
        "json-tagged",
        "plain",
        "uppercase-tag-is-content",
        "json5-tag",
        "space-before-tag",
        "empty-block",
        "six-backticks",
        "seven-backticks",
        "fence-as-content",
        "surrounded-by-prose",
        "multiple-blocks-with-unclosed-tail",
        "complete-then-unclosed",
        "unclosed-only",
        "several-opens-one-close",
        "close-fence-inside-content",
        "whitespace-variants",
    ],
)
def test_iter_fenced_blocks_matches_lazy_regex(text: str) -> None:
    assert list(iter_fenced_blocks(text)) == _FENCED_PATTERN.findall(text)


def test_iter_fenced_blocks_first_matches_regex_search() -> None:
    text = "intro ```\nfirst\n``` mid ```json\nsecond\n``` trailing ```\nnever"

    assert next(iter_fenced_blocks(text), None) == _FENCED_PATTERN.search(text).group(1)


@pytest.mark.parametrize("text", ["```json", "```json\n", "```"])
def test_iter_fenced_blocks_unclosed_finds_nothing(text: str) -> None:
    assert list(iter_fenced_blocks(text)) == []
    assert _FENCED_PATTERN.findall(text) == []


def test_iter_fenced_blocks_unclosed_large_input_returns_quickly() -> None:
    # An opening fence whose closing partner never arrives, followed by a
    # ~600k-char tail: no block may be reported and the scan must stay a
    # single bounded pass instead of re-scanning the tail.
    text = "```json\n" + "x" * 600_000

    started = time.perf_counter()
    blocks = list(iter_fenced_blocks(text))
    elapsed = time.perf_counter() - started

    assert blocks == []
    assert elapsed < 5.0


@pytest.mark.parametrize(
    "text",
    [
        "",
        "plain text",
        '<think>reasoning</think>{"a": 1}',
        '<think>k</think>\n<think>more</think>\n{"a": 1}',
        '<THINK>upper</THINK> {"a": 1}',
        '<think lang="x" scored>attrs</think>{"a": 1}',
        '<think>unclosed {"draft": true}',
        "<think>unclosed</think><think>also unclosed",
        "<think>a</think>   \n\t <think>b</think>   payload",
        "<thinker>not a think tag</thinker>",
        "<think>spans\nnewlines\n</think>\n\npayload",
    ],
    ids=[
        "empty",
        "no-tags",
        "single-block",
        "multiple-blocks",
        "case-insensitive",
        "attributes",
        "unclosed-keeps-text",
        "unclosed-pair-keeps-text",
        "whitespace-consumed",
        "word-boundary",
        "multiline",
    ],
)
def test_strip_leading_think_blocks_matches_anchored_regex_loop(text: str) -> None:
    assert strip_leading_think_blocks(text) == _strip_leading_reference(text)


@pytest.mark.parametrize(
    "text",
    [
        "",
        "plain text",
        '<think>reasoning</think>{"a": 1}',
        "<think>one</think> mid <think>two</think> tail",
        "<think>unclosed tail",
        "before <think>unclosed</THINK> case-sensitive",
        "</think> before open <think>ok</think>",
        "<think>first <think>nested-looking</think> rest</think> end",
        "<think>a</think><think>b</think>",
    ],
    ids=[
        "empty",
        "no-tags",
        "single-block",
        "multiple-blocks",
        "unclosed-kept",
        "case-sensitive-close",
        "close-before-open",
        "nested-looking",
        "adjacent-blocks",
    ],
)
def test_remove_think_blocks_matches_lazy_regex_sub(text: str) -> None:
    assert remove_think_blocks(text) == re.sub(r"<think>[\s\S]*?</think>", "", text)


def test_remove_think_blocks_unclosed_large_input_returns_quickly() -> None:
    text = "<think>never closed\n" * 40_000 + "tail without any closing tag"

    started = time.perf_counter()
    result = remove_think_blocks(text)
    elapsed = time.perf_counter() - started

    assert result == text
    assert elapsed < 5.0
