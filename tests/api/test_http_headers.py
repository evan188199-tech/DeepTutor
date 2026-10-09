"""Contract coverage for the shared Content-Disposition header builder (Top100 #55)."""

from __future__ import annotations

import re
from urllib.parse import unquote

from deeptutor.api.utils import http_headers
from deeptutor.api.utils.http_headers import content_disposition

_HEADER_SHAPE = re.compile(
    r"^(?P<disposition>[a-z]+); "
    r'filename="(?P<fallback>[^"]*)"; '
    r"filename\*=UTF-8''(?P<encoded>[!-~]+)$"
)


def _parts(header: str) -> tuple[str, str, str]:
    match = _HEADER_SHAPE.match(header)
    assert match is not None, header
    return match.group("disposition"), match.group("fallback"), match.group("encoded")


def test_ascii_name_passes_through_verbatim_in_both_parts() -> None:
    """A plain ASCII name needs no fallback or encoding machinery."""
    header = content_disposition("report-2026_v2.final.pdf")
    assert (
        header
        == "inline; filename=\"report-2026_v2.final.pdf\"; filename*=UTF-8''report-2026_v2.final.pdf"
    )


def test_disposition_defaults_to_inline_and_is_honored_verbatim() -> None:
    assert content_disposition("a.pdf").startswith("inline; ")
    assert content_disposition("a.pdf", disposition="attachment").startswith("attachment; ")


def test_non_ascii_name_degrades_to_question_marks_in_fallback_only() -> None:
    disposition, fallback, encoded = _parts(content_disposition("讲义.pdf"))
    assert disposition == "inline"
    assert fallback == "??.pdf"
    assert encoded == "%E8%AE%B2%E4%B9%89.pdf"
    assert unquote(encoded, encoding="utf-8") == "讲义.pdf"


def test_hostile_unicode_header_stays_latin1_encodable() -> None:
    """HTTP/1.1 headers are latin-1; this is the exact failure the builder exists to prevent."""
    header = content_disposition("讲义 – Émile 😀 L'Œuvre.pdf", disposition="attachment")
    header.encode("latin-1")
    disposition, fallback, encoded = _parts(header)
    assert disposition == "attachment"
    fallback.encode("ascii")
    assert "?" in fallback
    assert unquote(encoded, encoding="utf-8") == "讲义 – Émile 😀 L'Œuvre.pdf"


def test_quotes_and_backslashes_collapse_in_fallback_but_survive_in_filename_star() -> None:
    disposition, fallback, encoded = _parts(content_disposition('we"ird\\name.txt'))
    assert disposition == "inline"
    assert fallback == "we_ird_name.txt"
    assert encoded == "we%22ird%5Cname.txt"


def test_collapsed_fallback_keeps_the_quoted_string_well_formed() -> None:
    header = content_disposition('he said "hi" \\ ok.pdf')
    assert header.count('"') == 2


def test_empty_name_produces_empty_fallback_and_empty_filename_star() -> None:
    header = content_disposition("")
    assert header == "inline; filename=\"\"; filename*=UTF-8''"


def test_spaces_and_reserved_characters_are_percent_encoded_in_filename_star() -> None:
    _, fallback, encoded = _parts(content_disposition("a b/c+d~e(1).pdf"))
    assert fallback == "a b/c+d~e(1).pdf"
    assert encoded == "a%20b%2Fc%2Bd~e%281%29.pdf"


def test_filename_star_round_trips_varied_unicode_names() -> None:
    names = [
        "讲义.pdf",
        "naïve café.pdf",
        "Émile – L'Œuvre.pdf",
        "notes 😀 v2.pdf",
        "русский текст.txt",
    ]
    for name in names:
        _, _, encoded = _parts(content_disposition(name))
        assert unquote(encoded, encoding="utf-8") == name


def test_module_exports_only_the_builder() -> None:
    assert http_headers.__all__ == ["content_disposition"]
