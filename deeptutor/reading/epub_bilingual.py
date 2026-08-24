"""Explicit EPUB pairing and source-faithful bilingual revisions.

Pairing is deliberately two-step: DeepTutor recommends likely language
editions, but a reader confirms the pair before any derived material is
created. The generated revision copies the English EPUB untouched and inserts
collapsed translation blocks into its spine documents, so images, styles, and
spine order remain the source package's own.
"""

from __future__ import annotations

import hashlib
from html import escape, unescape
import io
import json
import os
from pathlib import Path
import re
import tempfile
import threading
from typing import Any
import uuid
import xml.etree.ElementTree as ET
import zipfile

from deeptutor.reading.extract import extract_material
from deeptutor.reading.models import MaterialManifest, ReadingError
from deeptutor.reading.store import ReadingStore

PAIRINGS_NAME = "_epub_pairings.json"
_PAIRING_WRITE_LOCK = threading.Lock()
_BLOCK_RE = re.compile(
    r"(<(?:p|li|blockquote)\b[^>]*>.*?</(?:p|li|blockquote)>)",
    re.I | re.S,
)
_BODY_RE = re.compile(r"<body\b[^>]*>(.*?)</body\s*>", re.I | re.S)
_BODY_CLOSE_RE = re.compile(r"</body\s*>", re.I)
_HEAD_CLOSE_RE = re.compile(r"</head\s*>", re.I)
_TAG_RE = re.compile(r"<[^>]+>")

_DETAIL_CSS = """<style type="text/css" data-deeptutor-bilingual="true">
details.dt-bilingual-zh { margin:.4em 0 1em; padding:.45em .75em; border-left:3px solid #2563eb; background:rgba(37,99,235,.06); border-radius:.35em; }
details.dt-bilingual-zh summary { cursor:pointer; color:#2563eb; font-weight:600; font-size:.9em; }
details.dt-bilingual-zh[data-low-confidence="true"] { border-left-color:#d97706; }
</style>""".strip()


def _local_name(tag: str) -> str:
    return tag.rsplit("}", 1)[-1].casefold()


def _metadata(epub: Path) -> dict[str, str]:
    """Read enough OPF metadata to rank, never to pair automatically."""
    try:
        with zipfile.ZipFile(epub) as archive:
            opf_name = next(name for name in archive.namelist() if name.casefold().endswith(".opf"))
            root = ET.fromstring(archive.read(opf_name))
    except (OSError, StopIteration, zipfile.BadZipFile, ET.ParseError):
        return {}

    wanted = ("title", "creator", "identifier", "language")
    values: dict[str, str] = {}
    for element in root.iter():
        name = _local_name(element.tag)
        if name in wanted and name not in values:
            values[name] = " ".join((element.text or "").split())
    return values


def _language(value: str) -> str:
    return value.strip().casefold().split("-", 1)[0]


def _tokens(value: str) -> set[str]:
    return set(re.findall(r"[\w\u3400-\u9fff]+", value.casefold()))


def _outline_titles(store: ReadingStore, material_id: str) -> set[str]:
    return {row.title.casefold() for row in store.outline(material_id) if row.title}


def recommend_epub_candidates(store: ReadingStore, material_id: str) -> list[dict[str, Any]]:
    """Return likely alternate-language editions for explicit confirmation."""
    source = store.manifest(material_id)
    _require_epub(source, "EPUB pairing")
    source_path = _raw_epub(store, material_id, "The source EPUB is unavailable.")
    source_meta = _metadata(source_path)
    source_titles = _outline_titles(store, material_id)
    source_language = _language(source_meta.get("language") or "")

    candidates: list[dict[str, Any]] = []
    for candidate in store.list_materials():
        if candidate.material_id == material_id or candidate.render_mode != "epub":
            continue
        try:
            candidate_path = _raw_epub(
                store, candidate.material_id, "The candidate EPUB is unavailable."
            )
        except ReadingError:
            continue
        metadata = _metadata(candidate_path)
        title_a = _tokens(source_meta.get("title") or source.title)
        title_b = _tokens(metadata.get("title") or candidate.title)
        title_score = len(title_a & title_b) / max(1, len(title_a | title_b))
        candidate_titles = _outline_titles(store, candidate.material_id)
        toc_score = len(source_titles & candidate_titles) / max(
            1, len(source_titles | candidate_titles)
        )
        identifier_match = bool(
            source_meta.get("identifier")
            and source_meta.get("identifier") == metadata.get("identifier")
        )
        author_match = bool(
            source_meta.get("author")
            and source_meta.get("author").casefold() == metadata.get("creator", "").casefold()
        )
        candidate_language = _language(metadata.get("language") or "")
        language_bonus = float(
            bool(source_language)
            and bool(candidate_language)
            and source_language != candidate_language
        )
        score = (
            0.4 * title_score
            + 0.2 * toc_score
            + 0.2 * float(identifier_match)
            + 0.1 * float(author_match)
            + 0.1 * language_bonus
        )
        candidates.append(
            {
                "material_id": candidate.material_id,
                "title": candidate.title,
                "filename": candidate.filename,
                "language": metadata.get("language", ""),
                "author": metadata.get("creator", ""),
                "score": round(score, 4),
                "reasons": {
                    "title": round(title_score, 4),
                    "toc": round(toc_score, 4),
                    "identifier": identifier_match,
                    "author": author_match,
                    "different_language": bool(language_bonus),
                },
            }
        )
    return sorted(candidates, key=lambda row: (-row["score"], row["title"]))


def _block_texts(document: str) -> list[str]:
    blocks = [
        unescape(_TAG_RE.sub("", match.group(1))).strip() for match in _BLOCK_RE.finditer(document)
    ]
    return [block for block in blocks if block]


def _details(text: str, *, low_confidence: bool) -> str:
    warning = " · 请检查对齐" if low_confidence else ""
    confidence = "true" if low_confidence else "false"
    return (
        f'<details class="dt-bilingual-zh" data-low-confidence="{confidence}">'
        f"<summary>显示中文{warning}</summary>"
        f"<div>{escape(text)}</div></details>"
    )


def _inject_chapter(
    source: str, translations: list[str], *, low_confidence_override: bool = False
) -> tuple[str, int]:
    low_confidence = low_confidence_override or (
        bool(translations) and len(translations) != len(_block_texts(source))
    )
    output: list[str] = []
    cursor = 0
    inserted = 0
    for index, match in enumerate(_BLOCK_RE.finditer(source)):
        output.append(source[cursor : match.end()])
        if index < len(translations):
            output.append("\n" + _details(translations[index], low_confidence=low_confidence))
            inserted += 1
        cursor = match.end()
    output.append(source[cursor:])
    merged = "".join(output)

    for translation in translations[inserted:]:
        merged = _BODY_CLOSE_RE.sub(
            _details(translation, low_confidence=True) + "\n</body>", merged, count=1
        )
        inserted += 1
    if inserted and "data-deeptutor-bilingual" not in merged:
        if _HEAD_CLOSE_RE.search(merged):
            merged = _HEAD_CLOSE_RE.sub(_DETAIL_CSS + "\n</head>", merged, count=1)
        else:
            body = _BODY_RE.search(merged)
            if body:
                merged = merged[: body.start()] + _DETAIL_CSS + body.group(0) + merged[body.end() :]
            else:
                merged = _DETAIL_CSS + merged
    return merged, inserted


def build_bilingual_epub(english: Path, chinese: Path) -> bytes:
    """Copy an English EPUB and add collapsed Chinese blocks by spine index."""
    english_extraction = extract_material(english)
    chinese_extraction = extract_material(chinese)
    if english_extraction.render_mode != "epub" or chinese_extraction.render_mode != "epub":
        raise ReadingError("Both pairing sources must be readable EPUB files.")
    if len(chinese_extraction.unit_refs) != len(chinese_extraction.units):
        raise ReadingError("The Chinese EPUB has an inconsistent spine contract.")
    translations = {
        index: text for index, text in enumerate(chinese_extraction.units, start=1) if text.strip()
    }
    count_mismatch = len(english_extraction.unit_refs) != len(translations)
    output_buffer = io.BytesIO()
    with (
        zipfile.ZipFile(english) as source,
        zipfile.ZipFile(chinese) as translation_book,
        zipfile.ZipFile(output_buffer, "w") as output,
    ):
        for info in source.infolist():
            data = source.read(info.filename)
            ref_index = next(
                (
                    index
                    for index, ref in enumerate(english_extraction.unit_refs, start=1)
                    if ref.source_href.lstrip("/") == info.filename.lstrip("/")
                ),
                None,
            )
            if ref_index in translations:
                href = chinese_extraction.unit_refs[ref_index - 1].source_href
                try:
                    document = translation_book.read(href).decode("utf-8", "replace")
                except KeyError:
                    document = chinese_extraction.units[ref_index - 1]
                xml = data.decode("utf-8", "replace")
                xml, _ = _inject_chapter(
                    xml,
                    _block_texts(document),
                    # Explicitly flag an index-only mapping so later alignment
                    # work can replace it without changing the material format.
                    low_confidence_override=count_mismatch,
                )
                data = xml.encode("utf-8")
            compression = zipfile.ZIP_STORED if info.filename == "mimetype" else info.compress_type
            output.writestr(info, data, compress_type=compression)
    return output_buffer.getvalue()


def _require_epub(manifest: MaterialManifest, action: str) -> None:
    if manifest.render_mode != "epub":
        raise ReadingError(f"{action} is only available for EPUB materials.")


def _raw_epub(store: ReadingStore, material_id: str, error: str) -> Path:
    path = store.raw_path(material_id)
    if path is None:
        raise ReadingError(error)
    return path


def _pairing_path(store: ReadingStore) -> Path:
    return store.root / PAIRINGS_NAME


def _atomic_write(path: Path, payload: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.parent / f".{path.name}.{uuid.uuid4().hex[:8]}.tmp"
    try:
        temporary.write_text(payload, encoding="utf-8")
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def list_epub_pairings(store: ReadingStore) -> list[dict[str, Any]]:
    try:
        rows = json.loads(_pairing_path(store).read_text(encoding="utf-8"))
    except (FileNotFoundError, OSError, json.JSONDecodeError):
        return []
    return rows if isinstance(rows, list) else []


def create_epub_pairing(
    store: ReadingStore, english_material_id: str, chinese_material_id: str
) -> tuple[dict[str, Any], MaterialManifest]:
    """Confirm a pair and ingest a derived, source-faithful EPUB revision."""
    english = store.manifest(english_material_id)
    chinese = store.manifest(chinese_material_id)
    _require_epub(english, "The English pairing source")
    _require_epub(chinese, "The Chinese pairing source")
    if english.material_id == chinese.material_id:
        raise ReadingError("Choose two different EPUB editions.")
    english_path = _raw_epub(store, english.material_id, "The English EPUB is unavailable.")
    chinese_path = _raw_epub(store, chinese.material_id, "The Chinese EPUB is unavailable.")
    english_language = _language(_metadata(english_path).get("language") or "")
    chinese_language = _language(_metadata(chinese_path).get("language") or "")
    if english_language == chinese_language:
        raise ReadingError("Pair an English EPUB with a different-language edition.")

    raw = build_bilingual_epub(english_path, chinese_path)
    pairing_id = hashlib.sha256(
        f"{english.material_id}\0{chinese.material_id}".encode("utf-8")
    ).hexdigest()[:16]
    with tempfile.TemporaryDirectory(prefix="dt-bilingual-epub-") as temporary:
        derived = Path(temporary) / f"{Path(english.filename).stem}-bilingual.epub"
        derived.write_bytes(raw)
        manifest = store.ingest(derived)

    row = {
        "pairing_id": pairing_id,
        "english_material_id": english.material_id,
        "chinese_material_id": chinese.material_id,
        "material_id": manifest.material_id,
        "status": "ready",
    }
    with _PAIRING_WRITE_LOCK:
        rows = [item for item in list_epub_pairings(store) if item.get("pairing_id") != pairing_id]
        rows.append(row)
        _atomic_write(_pairing_path(store), json.dumps(rows, ensure_ascii=False, indent=2))
    return row, manifest


def delete_epub_pairing(store: ReadingStore, pairing_id: str) -> bool:
    """Remove the pairing record, preserving the derived user material."""
    rows = list_epub_pairings(store)
    with _PAIRING_WRITE_LOCK:
        remaining = [row for row in rows if row.get("pairing_id") != pairing_id]
        if len(remaining) == len(rows):
            return False
        _atomic_write(_pairing_path(store), json.dumps(remaining, ensure_ascii=False, indent=2))
        return True


__all__ = [
    "build_bilingual_epub",
    "create_epub_pairing",
    "delete_epub_pairing",
    "list_epub_pairings",
    "recommend_epub_candidates",
]
