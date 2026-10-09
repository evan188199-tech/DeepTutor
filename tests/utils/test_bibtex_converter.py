from __future__ import annotations

import pytest

from deeptutor.utils.bibtex_converter import bibtex_to_markdown

SAMPLE_BIBTEX = r"""
@string{venue = {Advances}}

@article{vaswani2017attention,
  author = {Vaswani, Ashish and Shazeer, Noam},
  title = {Attention {Is} All You Need},
  journal = {Advances in Neural Information Processing Systems},
  year = {2017},
  doi = {10.5555/3295222},
  abstract = {The dominant models use recurrent networks.}
}

@inproceedings{devlin2019bert,
  author = {Devlin, Jacob and Chang, Ming-Wei},
  title = {"BERT": Pre-training of Deep Bidirectional Transformers},
  booktitle = {NAACL},
  year = 2019
}
"""


def test_bibtex_to_markdown_extracts_structured_entries() -> None:
    result = bibtex_to_markdown(SAMPLE_BIBTEX, "references")

    assert "Total entries: 2" in result
    assert "## 1. Attention Is All You Need" in result
    assert "**Authors:** Ashish Vaswani, Noam Shazeer" in result
    assert "**Type:** Journal Article" in result
    assert "10.5555/3295222" in result
    assert "The dominant models use recurrent networks." in result
    assert "@string" not in result
    assert '## 2. "BERT": Pre-training' in result
    assert "**Type:** Conference Paper" in result


def test_bibtex_to_markdown_keeps_value_with_nested_braces_intact() -> None:
    text = r"""
    @article{nested,
      title = {A {Nested {Title}} Here},
      year = {2020}
    }
    """

    result = bibtex_to_markdown(text)

    assert "A Nested Title Here" in result
    assert "2020" in result


def test_bibtex_to_markdown_skips_entry_with_unterminated_value() -> None:
    text = """
    @article{valid,
      title = {Valid Entry},
      year = {2020}
    }

    @article{broken,
      title = {Unterminated
    """

    result = bibtex_to_markdown(text)

    assert "Valid Entry" in result
    assert "broken" not in result


def test_bibtex_to_markdown_passes_non_bibtex_through() -> None:
    assert bibtex_to_markdown("not a bibliography") == "not a bibliography"


def test_bibtex_to_markdown_keeps_entry_with_accent_quote_in_braces() -> None:
    text = r"""
    @article{mueller2020,
      author = {M{\"u}ller, Hans and Smith, Jane},
      title = {Deep Learning},
      year = {2020}
    }

    @article{second2021,
      title = {Second Paper},
      year = {2021}
    }
    """

    result = bibtex_to_markdown(text)

    assert "Total entries: 2" in result
    assert "## 1. Deep Learning" in result
    assert "mueller2020" in result
    assert "## 2. Second Paper" in result


# ---------------------------------------------------------------------------
# Table-driven regression suite: normal / missing-field / malformed / unicode
# ---------------------------------------------------------------------------

NORMAL_PARSE_CASES = [
    pytest.param(
        "@article(paren2019, title = {Paren Entry}, year = {2019})",
        [
            "Total entries: 1",
            "## 1. Paren Entry",
            "**Type:** Journal Article",
            "**Citation key:** `paren2019`",
            "**Year:** 2019",
        ],
        [],
        id="paren-delimited-entry",
    ),
    pytest.param(
        '@article{quoted1, title = "Quoted Title", note = {kept}}',
        ["Total entries: 1", "## 1. Quoted Title", "**Note:** kept"],
        [],
        id="quoted-value-entry",
    ),
    pytest.param(
        "@misc{concat1, title = {Chain} # {Link}, year = 2021}",
        ["Total entries: 1", "## 1. ChainLink", "**Year:** 2021"],
        [],
        id="concatenated-values",
    ),
    pytest.param(
        "@article{multi1,\n  abstract = {Line one.\n    Line two.},\n  title = {Multiline}\n}",
        ["## 1. Multiline", "**Abstract:** Line one. Line two."],
        [],
        id="multiline-value-collapses-whitespace",
    ),
    pytest.param(
        "@comment{notes @article{fake, title = {Nope}} more}\n"
        "@string{venue = {Conf}}\n"
        "@article{real1, title = {Real Entry}}",
        ["Total entries: 1", "## 1. Real Entry"],
        ["fake", "Nope", "Conf"],
        id="metadata-entries-shield-nested-entry",
    ),
    pytest.param(
        "@article{labela, title = {T}}\n@fieldnote{labelb, title = {U}}",
        ["**Type:** Journal Article", "**Type:** Fieldnote"],
        [],
        id="known-and-unknown-type-labels",
    ),
]


@pytest.mark.parametrize(
    ("bibtex", "must_contain", "must_not_contain"),
    NORMAL_PARSE_CASES,
)
def test_bibtex_to_markdown_normal_entries_table(
    bibtex: str, must_contain: list[str], must_not_contain: list[str]
) -> None:
    result = bibtex_to_markdown(bibtex, "table")

    for fragment in must_contain:
        assert fragment in result
    for fragment in must_not_contain:
        assert fragment not in result


@pytest.mark.parametrize(
    ("entry_type", "expected_label"),
    [
        ("article", "Journal Article"),
        ("book", "Book"),
        ("inproceedings", "Conference Paper"),
        ("phdthesis", "PhD Thesis"),
        ("techreport", "Technical Report"),
        ("unpublished", "Unpublished"),
        ("misc", "Other"),
        ("fieldnote", "Fieldnote"),
    ],
)
def test_bibtex_to_markdown_type_label_table(entry_type: str, expected_label: str) -> None:
    text = f"@{entry_type}{{k1, title = {{T}}}}"

    result = bibtex_to_markdown(text)

    assert f"**Type:** {expected_label}" in result


MISSING_FIELD_CASES = [
    pytest.param(
        "@misc{bare,}",
        ["## 1. Untitled", "**Citation key:** `bare`", "**Type:** Other"],
        ["**Authors:**", "**Year:**", "**Journal:**"],
        id="no-fields-at-all",
    ),
    pytest.param(
        "@article{notitle, author = {A. Author}, year = {2000}}",
        ["## 1. Untitled", "**Authors:** A. Author", "**Year:** 2000"],
        [],
        id="missing-title-only",
    ),
    pytest.param(
        "@article{emptyf, title = {}, author = {}, year = {2022}}",
        ["## 1. Untitled", "**Year:** 2022"],
        ["**Authors:**"],
        id="empty-field-values-treated-as-missing",
    ),
    pytest.param(
        "@book{hiddenf, title = {Shown}, editor = {Ed Editor}, pages = {1--2}, volume = {3}}",
        ["## 1. Shown", "**Type:** Book", "**Citation key:** `hiddenf`"],
        ["Editor", "Pages", "Volume", "Ed Editor", "1--2"],
        id="non-display-fields-hidden",
    ),
]


@pytest.mark.parametrize(
    ("bibtex", "must_contain", "must_not_contain"),
    MISSING_FIELD_CASES,
)
def test_bibtex_to_markdown_missing_fields_table(
    bibtex: str, must_contain: list[str], must_not_contain: list[str]
) -> None:
    result = bibtex_to_markdown(bibtex, "table")

    for fragment in must_contain:
        assert fragment in result
    for fragment in must_not_contain:
        assert fragment not in result


@pytest.mark.parametrize(
    ("raw_author", "rendered_authors"),
    [
        ("Vaswani, Ashish and Shazeer, Noam", "Ashish Vaswani, Noam Shazeer"),
        ("Grace Hopper and Alan Turing", "Grace Hopper, Alan Turing"),
        ("Single Name", "Single Name"),
        ("Vaswani,   Ashish   and   Shazeer,   Noam", "Ashish Vaswani, Noam Shazeer"),
        (
            "Turing, A. M. and Hopper, Grace and Lovelace, Ada",
            "A. M. Turing, Grace Hopper, Ada Lovelace",
        ),
    ],
)
def test_bibtex_to_markdown_author_formatting_table(raw_author: str, rendered_authors: str) -> None:
    text = "@article{a1, author = {%s}, title = {T}}" % raw_author

    result = bibtex_to_markdown(text)

    assert f"**Authors:** {rendered_authors}" in result


MALFORMED_CASES = [
    pytest.param(
        '@article{good1, title = {OK Entry}}\n@article{badq, title = "never closed',
        1,
        ["Total entries: 1", "OK Entry"],
        ["badq"],
        id="unterminated-quoted-value-dropped",
    ),
    pytest.param(
        "@article{good2, title = {Fine}}\n@article{badb, title = {never closed",
        1,
        ["Total entries: 1", "Fine"],
        ["badb"],
        id="unterminated-braced-value-dropped",
    ),
    pytest.param(
        "@article{good3, title = {Kept}}\n@article{nocomma}",
        1,
        ["Total entries: 1", "Kept"],
        ["nocomma"],
        id="entry-without-comma-dropped",
    ),
    pytest.param(
        "@article{good4, title = {Alive}}\n@article{emptyv, title = , year = {2020}}",
        1,
        ["Total entries: 1", "Alive"],
        ["emptyv"],
        id="empty-bare-value-dropped",
    ),
    pytest.param(
        "garbage prefix !! @article{good5, title = {Survivor}} trailing junk",
        1,
        ["Total entries: 1", "Survivor"],
        ["trailing junk"],
        id="junk-around-valid-entry-ignored",
    ),
]


@pytest.mark.parametrize(
    ("bibtex", "entry_count", "must_contain", "must_not_contain"),
    MALFORMED_CASES,
)
def test_bibtex_to_markdown_malformed_entries_table(
    bibtex: str, entry_count: int, must_contain: list[str], must_not_contain: list[str]
) -> None:
    result = bibtex_to_markdown(bibtex, "table")

    assert f"Total entries: {entry_count}" in result
    for fragment in must_contain:
        assert fragment in result
    for fragment in must_not_contain:
        assert fragment not in result


def test_bibtex_to_markdown_only_malformed_entries_returns_source() -> None:
    text = '@article{onlybad, title = "unclosed'

    result = bibtex_to_markdown(text)

    assert result == text


UNICODE_CASES = [
    pytest.param(
        "@article{cjk1, author = {张三 and 李四}, title = {深度学习导论}, year = {2023}}",
        ["## 1. 深度学习导论", "**Authors:** 张三, 李四", "**Year:** 2023"],
        [],
        id="cjk-fields-survive",
    ),
    pytest.param(
        "@article{diac1, author = {Müller, Hans and Émile Dubois}, title = {Über den Wolken}}",
        ["## 1. Über den Wolken", "**Authors:** Hans Müller, Émile Dubois"],
        [],
        id="precomposed-diacritics-survive",
    ),
    pytest.param(
        r"@article{esc1, title = {Rock \& Roll}}",
        [r"## 1. Rock \& Roll"],
        [],
        id="backslash-escapes-preserved",
    ),
    pytest.param(
        r"@article{key`with, title = {T}}",
        ["**Citation key:** `key'with`"],
        [],
        id="backtick-in-citation-key-normalised",
    ),
    pytest.param(
        "@article{braced1, title = {{Double} Braced {Name}}}",
        ["## 1. Double Braced Name"],
        [],
        id="nested-braces-stripped-from-value",
    ),
]


@pytest.mark.parametrize(
    ("bibtex", "must_contain", "must_not_contain"),
    UNICODE_CASES,
)
def test_bibtex_to_markdown_unicode_and_special_chars_table(
    bibtex: str, must_contain: list[str], must_not_contain: list[str]
) -> None:
    result = bibtex_to_markdown(bibtex, "table")

    for fragment in must_contain:
        assert fragment in result
    for fragment in must_not_contain:
        assert fragment not in result


@pytest.mark.parametrize(
    "source",
    [
        "plain text with no bibtex markers",
        "",
        "@article without delimiter",
        "@123{numeric_entry_start}",
    ],
)
def test_bibtex_to_markdown_non_bibtex_passthrough_table(source: str) -> None:
    assert bibtex_to_markdown(source) == source


def test_bibtex_to_markdown_display_fields_render_in_documented_order() -> None:
    text = (
        "@article{order1, keywords = {kw}, url = {https://e.io}, doi = {10.1/x},"
        " journal = {J}, author = {A. One}, year = {1999}, abstract = {Abs}, note = {N}}"
    )

    result = bibtex_to_markdown(text)

    markers = [
        "**Authors:**",
        "**Year:**",
        "**Journal:**",
        "**DOI:**",
        "**URL:**",
        "**Abstract:**",
        "**Keywords:**",
        "**Note:**",
    ]
    positions = [result.index(marker) for marker in markers]
    assert positions == sorted(positions)
