"""A shared reading session over one confirmed bilingual EPUB pairing.

This module only *consumes* the pairing records written by
:mod:`deeptutor.reading.epub_bilingual` (#979); it never rewrites them. On top
of a confirmed pair it provides the two halves of the linked bilingual
reading experience that need no model at all:

* **Shared progress** — saving a viewport on one edition mirrors a mapped
  viewport onto the opposite edition, so reloading either side restores the
  same place in the book.
* **Aligned excerpts** — a selected sentence or paragraph is located in its
  own section, the section is mapped to the opposite edition, and the
  positionally aligned paragraph is returned verbatim. When the structure
  does not support an alignment, the result says so and carries no text:
  a wrong paragraph is worse than none.
"""

from __future__ import annotations

from typing import Any

from deeptutor.reading.epub_bilingual import list_epub_pairings
from deeptutor.reading.models import ReadingError, ReadingPosition
from deeptutor.reading.store import ReadingStore

#: Upper bound for a served excerpt, so a runaway paragraph cannot become a
#: response-size problem. Callers may pass a smaller budget.
MAX_ALIGNED_EXCERPT_CHARS = 4000


def pairing_for_material(store: ReadingStore, material_id: str) -> dict[str, Any] | None:
    """The confirmed pairing that includes *material_id*, if there is one."""
    for row in list_epub_pairings(store):
        if row.get("status") != "confirmed":
            continue
        if material_id in (row.get("english_material_id"), row.get("chinese_material_id")):
            return row
    return None


def opposite_material_id(pairing: dict[str, Any], material_id: str) -> str | None:
    """The other edition of *pairing*, or ``None`` for a foreign material."""
    english = str(pairing.get("english_material_id") or "")
    chinese = str(pairing.get("chinese_material_id") or "")
    if material_id == english:
        return chinese or None
    if material_id == chinese:
        return english or None
    return None


def map_locator(store: ReadingStore, source_id: str, target_id: str, locator: int) -> int | None:
    """Map a unit locator between paired editions by relative position.

    Editions that split the same book into the same number of sections map
    one-to-one. Editions that split it differently are mapped
    proportionally: section 3 of 4 in a six-section translation lands at
    section 4, never at a section the ratio excludes. ``None`` means the
    locator cannot be mapped honestly.
    """
    try:
        source = store.manifest(source_id)
        target = store.manifest(target_id)
    except ReadingError:
        return None
    if source.unit_count < 1 or target.unit_count < 1:
        return None
    if not 1 <= locator <= source.unit_count:
        return None
    if source.unit_count == target.unit_count:
        return locator
    if source.unit_count == 1:
        return 1
    ratio = (locator - 1) / (source.unit_count - 1)
    return 1 + round(ratio * (target.unit_count - 1))


def mirror_pair_position(
    store: ReadingStore, material_id: str, position: ReadingPosition
) -> dict[str, Any] | None:
    """Propagate a saved viewport to the opposite edition of the pair.

    Returns ``None`` when the material is not in a confirmed pairing — the
    common case, and not an error. Otherwise returns a summary whose
    ``mirrored`` flag says whether the opposite edition now carries the
    shared viewport; a mapping failure is reported, never guessed around.
    """
    pairing = pairing_for_material(store, material_id)
    if pairing is None:
        return None
    other_id = opposite_material_id(pairing, material_id) or ""
    summary: dict[str, Any] = {
        "pairing_id": str(pairing.get("pairing_id") or ""),
        "opposite_material_id": other_id,
    }
    mapped = map_locator(store, material_id, other_id, position.locator)
    if mapped is None:
        return {**summary, "mirrored": False, "reason": "unmappable_locator"}
    mirrored = store.save_position(
        other_id,
        ReadingPosition(locator=mapped, source_anchor="", percentage=position.percentage),
    )
    return {
        **summary,
        "mirrored": True,
        "opposite_locator": mirrored.locator,
        "opposite_percentage": mirrored.percentage,
    }


def _paragraphs(text: str) -> list[str]:
    """Non-empty lines of a unit, which is how EPUB paragraphs are stored."""
    return [line.strip() for line in text.split("\n") if line.strip()]


def _normalize(text: str) -> str:
    return " ".join(text.split())


def aligned_excerpt(
    store: ReadingStore,
    material_id: str,
    *,
    locator: int,
    quote: str,
    max_chars: int = MAX_ALIGNED_EXCERPT_CHARS,
) -> dict[str, Any]:
    """Serve the aligned opposite-side paragraph for a selection, no model.

    The quote is matched inside its own section first; only a paragraph that
    contains the selection can be aligned. The opposite paragraph is then
    chosen positionally: identical paragraph counts map one-to-one, and any
    structural mismatch is reported as an explicit failure with no excerpt,
    because a guessed paragraph would be unrelated text. A selection that
    covers only part of its paragraph is served the whole aligned paragraph
    with ``degraded=True`` — the documented paragraph-level fallback.
    """
    result: dict[str, Any] = {
        "status": "",
        "granularity": "",
        "degraded": False,
        "excerpt": "",
        "excerpt_truncated": False,
        "opposite_locator": 0,
    }
    pairing = pairing_for_material(store, material_id)
    if pairing is None:
        return {**result, "status": "unpaired"}
    other_id = opposite_material_id(pairing, material_id) or ""
    result["pairing_id"] = str(pairing.get("pairing_id") or "")
    result["opposite_material_id"] = other_id

    normalized = _normalize(quote)
    if not normalized:
        return {**result, "status": "empty_selection"}

    try:
        source = store.manifest(material_id)
        opposite = store.manifest(other_id)
        own_paragraphs = _paragraphs(store.unit_text(material_id, locator))
        mapped = map_locator(store, material_id, other_id, locator)
        if mapped is None:
            return {**result, "status": "unmappable_section"}
        opposite_paragraphs = _paragraphs(store.unit_text(other_id, mapped))
    except ReadingError:
        return {**result, "status": "section_unavailable"}

    index = next(
        (
            position
            for position, paragraph in enumerate(own_paragraphs)
            if normalized in _normalize(paragraph)
        ),
        None,
    )
    if index is None:
        return {**result, "status": "quote_not_found"}

    if len(own_paragraphs) != len(opposite_paragraphs) or index >= len(opposite_paragraphs):
        return {**result, "status": "paragraph_unaligned"}

    excerpt = opposite_paragraphs[index]
    truncated = len(excerpt) > max_chars
    if truncated:
        excerpt = excerpt[:max_chars]
    language = "zh" if other_id == str(pairing.get("chinese_material_id") or "") else "en"
    return {
        **result,
        "status": "aligned",
        "granularity": "paragraph",
        "degraded": normalized != _normalize(own_paragraphs[index]),
        "excerpt": excerpt,
        "excerpt_truncated": truncated,
        "opposite_locator": mapped,
        "opposite_title": opposite.title,
        "opposite_language": language,
        "source_locator": locator,
        "source_unit": source.unit,
    }


__all__ = [
    "MAX_ALIGNED_EXCERPT_CHARS",
    "aligned_excerpt",
    "map_locator",
    "mirror_pair_position",
    "opposite_material_id",
    "pairing_for_material",
]
