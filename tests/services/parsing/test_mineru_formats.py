"""Unit contract for the MinerU version floor and input-format routing tables.

Pure in-memory checks: no subprocesses, no network, no installed MinerU needed.
"""

from __future__ import annotations

import pytest

from deeptutor.services.parsing.engines.mineru import formats

EXPECTED_PDF = frozenset({".pdf"})
EXPECTED_IMAGE = frozenset(
    {".bmp", ".gif", ".jp2", ".jpeg", ".jpg", ".png", ".tiff", ".webp"}
)
EXPECTED_OFFICE = frozenset({".docx", ".pptx", ".xlsx"})
EXPECTED_GROUPS = {
    "MINERU_PDF_FORMATS": EXPECTED_PDF,
    "MINERU_IMAGE_FORMATS": EXPECTED_IMAGE,
    "MINERU_OFFICE_FORMATS": EXPECTED_OFFICE,
}


def test_public_exports_cover_the_module_api() -> None:
    assert set(formats.__all__) == {
        "MIN_MINERU_VERSION",
        "MINERU_IMAGE_FORMATS",
        "MINERU_OFFICE_FORMATS",
        "MINERU_PDF_FORMATS",
        "MINERU_SUPPORTED_FORMATS",
        "mineru_version_is_current",
    }
    for name in formats.__all__:
        assert hasattr(formats, name)


def test_min_version_floor_is_pinned() -> None:
    assert formats.MIN_MINERU_VERSION == "3.4.5"


@pytest.mark.parametrize("group_name", sorted(EXPECTED_GROUPS))
def test_format_groups_match_the_supported_cli_contract(group_name: str) -> None:
    group = getattr(formats, group_name)
    assert isinstance(group, frozenset)
    assert group == EXPECTED_GROUPS[group_name]
    for suffix in group:
        assert suffix.startswith(".")
        assert suffix == suffix.lower()
        assert not any(char.isspace() for char in suffix)


def test_format_groups_are_pairwise_disjoint() -> None:
    pdf = formats.MINERU_PDF_FORMATS
    image = formats.MINERU_IMAGE_FORMATS
    office = formats.MINERU_OFFICE_FORMATS
    assert pdf.isdisjoint(image)
    assert pdf.isdisjoint(office)
    assert image.isdisjoint(office)


def test_supported_formats_is_union_of_declared_groups() -> None:
    assert formats.MINERU_SUPPORTED_FORMATS == (
        formats.MINERU_PDF_FORMATS
        | formats.MINERU_IMAGE_FORMATS
        | formats.MINERU_OFFICE_FORMATS
    )
    assert formats.MINERU_SUPPORTED_FORMATS == (
        EXPECTED_PDF | EXPECTED_IMAGE | EXPECTED_OFFICE
    )


@pytest.mark.parametrize(
    ("version_text", "expected"),
    [
        ("3.4.5", True),  # exactly the floor
        ("3.4.6", True),
        ("3.5", True),  # short release is zero-padded to the floor width
        ("4.0", True),
        ("10.0", True),  # components compare numerically, not lexicographically
        ("v3.4.5", True),
        ("03.04.05", True),  # leading zeros normalize numerically
        ("3.4.5rc1", True),  # pre-release tag after the parsed release
        ("3.4.5.dev0", True),
        ("MinerU-CLI 3.6.1 (build 2026.09.01)", True),  # first dotted pair decides
        ("3.4.4", False),
        ("3.4", False),  # padded to 3.4.0, below the floor
        ("2.9.9", False),
        ("1.2.3.4", False),
        ("mineru-py 2.1.0 requires cli>=3.4.5", False),  # earliest dotted pair wins
        ("mineru 3", False),  # single-component releases never match
        ("", False),
        ("   ", False),
        ("mineru (unknown version)", False),
        (None, False),
        (0, False),
    ],
)
def test_version_floor_decision(version_text: object, expected: bool) -> None:
    assert formats.mineru_version_is_current(version_text) is expected


def test_floor_is_self_consistent_with_the_version_predicate() -> None:
    assert formats.mineru_version_is_current(formats.MIN_MINERU_VERSION) is True
