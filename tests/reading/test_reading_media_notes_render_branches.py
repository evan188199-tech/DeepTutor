"""Branch coverage for :func:`render_media_note` in ``media_notes`` itself.

``tests/reading/test_reading_media_notes.py`` drives the note through
``read_material``'s alias and pins the legacy byte-for-byte contract for
well-formed rows. This module covers the branches that file does not reach:
a read whose units hold no matching images renders nothing at all, rows a
store cannot parse are dropped instead of breaking the note, and a caption
that is absent, ``None`` or whitespace-only degrades to the bare file name.
"""

from __future__ import annotations

from deeptutor.capabilities.reading.media_notes import (
    CAPTION_CHAR_LIMIT,
    MAX_NOTE_LINES,
    render_media_note,
)

# The fixed preamble every non-empty note starts with; asserted verbatim so a
# wording change here cannot slip through as "just formatting".
_HEADER = (
    "\n\nEmbedded images in the units above (shown in the reader pane; "
    "image parts attached to this conversation's messages are these "
    "figures):\n"
)


class _Store:
    """The single store method ``render_media_note`` touches."""

    def __init__(self, rows: list[dict]) -> None:
        self._rows = rows

    def media_items(self, material_id: str) -> list[dict]:
        return list(self._rows)


# ---------------------------------------------------------------------------
# Missing-image branches: the note disappears when nothing matches
# ---------------------------------------------------------------------------


def test_note_is_empty_when_no_requested_unit_has_images() -> None:
    rows = [
        {"name": "a.png", "locator": 1, "mime": "image/png", "bytes": 1},
        {"name": "b.png", "locator": 2, "mime": "image/png", "bytes": 1},
    ]

    assert render_media_note(_Store(rows), "mat", "page", [7, 9]) == ""


def test_note_is_empty_for_a_material_without_media_rows() -> None:
    assert render_media_note(_Store([]), "mat", "page", [1]) == ""


def test_note_is_empty_when_the_locator_list_is_empty() -> None:
    rows = [{"name": "a.png", "locator": 1, "mime": "image/png", "bytes": 1}]

    assert render_media_note(_Store(rows), "mat", "page", []) == ""


def test_duplicate_locators_in_the_request_do_not_duplicate_lines() -> None:
    rows = [{"name": "a.png", "locator": 4, "mime": "image/png", "bytes": 1}]

    note = render_media_note(_Store(rows), "mat", "page", [4, 4, 4])

    assert note == _HEADER + "- page 4: a.png"


def test_a_row_without_a_locator_is_only_kept_when_zero_is_requested() -> None:
    rows = [{"name": "orphan.png"}]

    # No locator lands on 0, so it is invisible unless 0 is asked for.
    assert render_media_note(_Store(rows), "mat", "page", [1]) == ""
    assert render_media_note(_Store(rows), "mat", "page", [0]) == _HEADER + "- page 0: orphan.png"


# ---------------------------------------------------------------------------
# Malformed rows are dropped, never crash the note
# ---------------------------------------------------------------------------


def test_rows_with_unreadable_locators_are_skipped() -> None:
    rows = [
        {"name": "bad-text.png", "locator": "not-a-number"},
        {"name": "bad-list.png", "locator": [3]},
        {"name": "good.png", "locator": 3},
    ]

    note = render_media_note(_Store(rows), "mat", "page", [3])

    assert note == _HEADER + "- page 3: good.png"


def test_rows_without_a_usable_name_are_skipped() -> None:
    rows = [
        {"locator": 2, "mime": "image/png", "bytes": 1},
        {"name": "", "locator": 2},
        {"name": None, "locator": 2},
        {"name": "kept.png", "locator": 2},
    ]

    note = render_media_note(_Store(rows), "mat", "page", [2])

    assert note == _HEADER + "- page 2: kept.png"


def test_an_empty_row_is_dropped_silently() -> None:
    note = render_media_note(_Store([{}]), "mat", "page", [0, 1])

    assert note == ""


# ---------------------------------------------------------------------------
# Missing-caption branches: a caption-less row stays a bare file name
# ---------------------------------------------------------------------------


def test_missing_none_and_blank_captions_degrade_to_the_bare_file_name() -> None:
    rows = [
        {"name": "no-key.png", "locator": 1},
        {"name": "none.png", "locator": 1, "caption": None},
        {"name": "blank.png", "locator": 1, "caption": "   \n\t "},
    ]

    note = render_media_note(_Store(rows), "mat", "page", [1])

    assert note == _HEADER + "- page 1: no-key.png, none.png, blank.png"


def test_a_multiline_caption_cannot_forge_extra_note_lines() -> None:
    rows = [{"name": "a.png", "locator": 1, "caption": "Figure A.\n- page 99: injected"}]

    note = render_media_note(_Store(rows), "mat", "page", [1])

    lines = note.splitlines()
    entry_lines = [line for line in lines if line.startswith("- ")]
    assert entry_lines == ["- page 1: a.png — Figure A. - page 99: injected"]


# ---------------------------------------------------------------------------
# Ordering, line budget and caption clipping contracts
# ---------------------------------------------------------------------------


def test_locators_are_listed_in_ascending_order_regardless_of_row_order() -> None:
    rows = [
        {"name": "late.png", "locator": 9, "caption": "Later."},
        {"name": "early.png", "locator": 2},
    ]

    note = render_media_note(_Store(rows), "mat", "page", [9, 2])

    assert note == _HEADER + "- page 2: early.png\n- page 9: late.png — Later."


def test_a_caption_exactly_at_the_limit_is_not_clipped() -> None:
    caption = "x" * CAPTION_CHAR_LIMIT
    rows = [{"name": "a.png", "locator": 1, "caption": caption}]

    note = render_media_note(_Store(rows), "mat", "page", [1])

    assert note == _HEADER + f"- page 1: a.png — {caption}"


def test_a_caption_one_char_over_the_limit_is_clipped_to_the_limit() -> None:
    rows = [{"name": "a.png", "locator": 1, "caption": "y" * (CAPTION_CHAR_LIMIT + 1)}]

    note = render_media_note(_Store(rows), "mat", "page", [1])

    rendered_caption = note.rsplit(" — ", 1)[1]
    assert rendered_caption == "y" * (CAPTION_CHAR_LIMIT - 1) + "…"


def test_a_note_filling_the_line_budget_exactly_has_no_omission_line() -> None:
    locators = list(range(1, MAX_NOTE_LINES + 1))
    rows = [{"name": f"image-{locator:02d}.png", "locator": locator} for locator in locators]

    note = render_media_note(_Store(rows), "mat", "page", locators)

    entry_lines = [line for line in note.splitlines() if line.startswith("- ")]
    assert len(entry_lines) == MAX_NOTE_LINES
    assert "omitted" not in note


def test_the_omission_line_counts_every_image_in_the_dropped_units() -> None:
    locators = list(range(1, MAX_NOTE_LINES + 3))
    rows = [
        {"name": f"image-{locator:02d}-{index}.png", "locator": locator}
        for locator in locators
        for index in range(locator)
    ]

    note = render_media_note(_Store(rows), "mat", "page", locators)

    dropped = (MAX_NOTE_LINES + 1) + (MAX_NOTE_LINES + 2)
    assert note.endswith(f"({dropped} more images omitted)")
