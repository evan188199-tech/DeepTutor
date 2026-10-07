"""Delimited-block extraction that avoids lazy regex re-scanning.

Model output can be large and is not always well formed: when a closing
delimiter never arrives, lazy regexes such as
`````(?:json)?\\s*([\\s\\S]*?)\\s*``` ```` re-scan the remaining text from
every opening delimiter, which degrades quadratically on long streamed
answers. The helpers here locate delimiters with literal searches and give
up at the first unclosed block, so a malformed tail costs one linear pass.
Success-path results match the regexes they replace.
"""

from __future__ import annotations

from collections.abc import Iterator
import re

_FENCE = "```"
_TAG_JSON = "json"
_THINK_TAG = "<think>"
_THINK_CLOSE = "</think>"
_THINK_CLOSE_LEN = len(_THINK_CLOSE)
_LEADING_THINK_OPEN = re.compile(r"<think\b[^>]*>", re.IGNORECASE)
_LEADING_THINK_CLOSE = re.compile(_THINK_CLOSE, re.IGNORECASE)


def _skip_whitespace(text: str, pos: int) -> int:
    """Index of the first non-whitespace character at or after ``pos``.

    ``str.isspace`` accepts exactly the characters the regex ``\\s`` class
    matches, so this mirrors greedy ``\\s*`` consumption.
    """
    limit = len(text)
    while pos < limit and text[pos].isspace():
        pos += 1
    return pos


def iter_fenced_blocks(text: str) -> Iterator[str]:
    """Yield the contents of complete triple-backtick fenced blocks, in order.

    Equivalent to ``re.findall(r"```(?:json)?\\s*([\\s\\S]*?)\\s*```", text)``
    (use ``next(..., None)`` for the ``re.search`` variant): an optional
    ``json`` tag and the whitespace around the content are excluded. Iteration
    stops at the first fence without a closing partner — the same point where
    the regex can no longer match — without re-scanning the unclosed tail.
    """
    pos = 0
    while (start := text.find(_FENCE, pos)) != -1:
        inner = start + len(_FENCE)
        if text.startswith(_TAG_JSON, inner):
            inner += len(_TAG_JSON)
        inner = _skip_whitespace(text, inner)
        close = text.find(_FENCE, inner)
        if close == -1:
            return
        yield text[inner:close].rstrip()
        pos = close + len(_FENCE)


def strip_leading_think_blocks(text: str) -> str:
    """Drop leading complete ``<think ...>`` blocks, case-insensitively.

    Mirrors looping ``re.match(r"<think\\b[^>]*>.*?</think>\\s*", text,
    re.DOTALL | re.IGNORECASE)``: each removed block spans from an opening
    tag to the first closing tag after it plus trailing whitespace, and an
    unterminated leading block stops the stripping and is kept verbatim,
    together with everything after it.
    """
    while (open_match := _LEADING_THINK_OPEN.match(text)) is not None:
        close_match = _LEADING_THINK_CLOSE.search(text, open_match.end())
        if close_match is None:
            return text
        text = text[close_match.end() :].lstrip()
    return text


def remove_think_blocks(text: str) -> str:
    """Remove every complete case-sensitive ``<think>`` block.

    Mirrors ``re.sub(r"<think>[\\s\\S]*?</think>", "", text)``: each removal
    spans from an opening tag to the first closing tag after it, and an
    unclosed opening tag keeps the rest of the text unchanged.
    """
    parts: list[str] = []
    pos = 0
    while (start := text.find(_THINK_TAG, pos)) != -1:
        close = text.find(_THINK_CLOSE, start + len(_THINK_TAG))
        if close == -1:
            break
        parts.append(text[pos:start])
        pos = close + _THINK_CLOSE_LEN
    parts.append(text[pos:])
    return "".join(parts)


__all__ = ["iter_fenced_blocks", "remove_think_blocks", "strip_leading_think_blocks"]
