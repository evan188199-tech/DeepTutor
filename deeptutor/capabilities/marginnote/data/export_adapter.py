"""Parse a MarginNote 4 Markdown / OPML export folder."""

from __future__ import annotations

from dataclasses import replace
import os
import hashlib
import re
from pathlib import Path
from typing import Any
from xml.etree import ElementTree as ET

import yaml

from deeptutor.capabilities.marginnote.data.base import (
    AdapterError,
    DocumentInfo,
    Highlight,
    MarginNoteAdapter,
    MindMapNode,
    Note,
    Notebook,
)
from deeptutor.capabilities.marginnote.data.diagnostics import (
    WRITE_MODE_IMPORT_QUEUE,
    AdapterCapabilities,
    AdapterDiagnostics,
    ParseWarning,
    display_name_for,
)

WRITEBACK_DIRNAME = "deeptutor-notes"
IGNORED_DIRS = frozenset({".git", ".obsidian", ".trash", WRITEBACK_DIRNAME})
_TAG_RE = re.compile(r"(?:^|(?<=\s))#([A-Za-z0-9_][A-Za-z0-9_/-]*)")
_PAGE_RE = re.compile(
    r"\((?:p(?:age)?\.?\s*|P)(\d+)\)|(?:(?<![A-Za-z])p(?:age)?\.?\s*)(\d+)",
    re.IGNORECASE,
)
_COLOR_RE = re.compile(r"\[(?:color|colour)\s*[:=]\s*([^\]]+)\]", re.IGNORECASE)
_FRONTMATTER_RE = re.compile(r"\A---\s*\n(.*?)\n---\s*\n?", re.DOTALL)
_IMAGE_RE = re.compile(r"!\[[^\]]*\]\([^)]+\)")


def _stable_id(*parts: str) -> str:
    raw = "|".join(parts)
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()[:12]


def _extract_tags(text: str) -> list[str]:
    seen: dict[str, None] = {}
    for tag in _TAG_RE.findall(text or ""):
        seen.setdefault(tag, None)
    return list(seen)


def _extract_page(text: str) -> int | None:
    match = _PAGE_RE.search(text or "")
    if not match:
        return None
    value = match.group(1) or match.group(2)
    return int(value) if value else None


def _extract_color(text: str) -> str:
    match = _COLOR_RE.search(text or "")
    return match.group(1).strip() if match else ""


def _strip_markup(text: str) -> str:
    cleaned = _COLOR_RE.sub("", text or "")
    cleaned = _PAGE_RE.sub("", cleaned)
    return re.sub(r"\s+", " ", cleaned).strip()


def _rel(root: Path, path: Path) -> str:
    return path.relative_to(root).as_posix()


def _is_ignored(rel: Path) -> bool:
    return any(part in IGNORED_DIRS for part in rel.parts)


def _safe_join(root: Path, rel: str) -> Path:
    root_resolved = root.resolve()
    candidate = (root_resolved / rel.lstrip("/")).resolve()
    if candidate != root_resolved and root_resolved not in candidate.parents:
        raise AdapterError(f"Path {rel!r} escapes the notebook.")
    return candidate


def _with_md_suffix(rel: str) -> str:
    return rel if rel.lower().endswith(".md") else f"{rel}.md"


def _compose_note(frontmatter: dict[str, Any], body: str) -> str:
    body = body or ""
    if not frontmatter:
        return body if body.endswith("\n") or not body else body + "\n"
    dumped = yaml.safe_dump(frontmatter, allow_unicode=True, sort_keys=False).strip()
    text = f"---\n{dumped}\n---\n\n{body.lstrip()}"
    return text if text.endswith("\n") else text + "\n"


def split_frontmatter(text: str) -> tuple[dict[str, Any], str]:
    match = _FRONTMATTER_RE.match(text)
    if not match:
        return {}, text
    try:
        data = yaml.safe_load(match.group(1)) or {}
    except yaml.YAMLError:
        return {}, text
    if not isinstance(data, dict):
        return {}, text
    return data, text[match.end() :]


class ExportAdapter(MarginNoteAdapter):
    """v1 adapter: Markdown highlights/notes + OPML mind maps."""

    def __init__(self, notebook_path: str, writeback_path: str = "") -> None:
        super().__init__(notebook_path, writeback_path)
        self._root = Path(notebook_path).expanduser()
        if not self._root.is_dir():
            raise AdapterError(f"Notebook path is not a directory: {notebook_path}")
        self._write_root = (
            Path(writeback_path).expanduser()
            if writeback_path
            else self._root / WRITEBACK_DIRNAME
        )
        self._signature: tuple[tuple[str, int, int], ...] | None = None
        self._notebook: Notebook | None = None
        self._warnings: list[ParseWarning] = []
        self.adapter_name = "export"

    def load(self) -> Notebook:
        signature = self._scan_signature()
        if self._notebook is None or signature != self._signature:
            self._notebook = self._parse()
            self._signature = signature
        return self._notebook

    def search(self, query: str, *, tag: str = "", limit: int = 20) -> list[dict[str, Any]]:
        notebook = self.load()
        needle = (query or "").strip().lower()
        wanted_tag = (tag or "").strip().lstrip("#").lower()
        if not needle and not wanted_tag:
            raise AdapterError("search needs a query or a tag.")
        hits: list[dict[str, Any]] = []
        for highlight in notebook.highlights:
            if wanted_tag and wanted_tag not in {item.lower() for item in highlight.tags}:
                continue
            hay = f"{highlight.text} {highlight.document_name} {highlight.section}".lower()
            if needle and needle not in hay:
                continue
            hits.append({"kind": "highlight", **highlight.to_dict()})
            if len(hits) >= limit:
                return hits
        for note in notebook.notes:
            if wanted_tag and wanted_tag not in {item.lower() for item in note.tags}:
                continue
            hay = f"{note.text} {note.document_name} {note.section}".lower()
            if needle and needle not in hay:
                continue
            hits.append({"kind": "note", **note.to_dict()})
            if len(hits) >= limit:
                return hits
        for node in notebook.mindmap:
            hay = f"{node.title} {node.note}".lower()
            if needle and needle not in hay:
                continue
            if wanted_tag:
                continue
            hits.append({"kind": "mindmap", **node.to_dict()})
            if len(hits) >= limit:
                break
        return hits

    def read_item(self, item_id: str) -> dict[str, Any]:
        notebook = self.load()
        item_id = (item_id or "").strip()
        if not item_id:
            raise AdapterError("read_item needs an id.")
        for highlight in notebook.highlights:
            if highlight.id == item_id:
                neighbors = [
                    item.to_dict()
                    for item in notebook.highlights
                    if item.document_id == highlight.document_id
                ]
                index = next(
                    (i for i, item in enumerate(neighbors) if item["id"] == highlight.id),
                    0,
                )
                note = next((n for n in notebook.notes if n.id == highlight.note_id), None)
                return {
                    "kind": "highlight",
                    "item": highlight.to_dict(),
                    "note": note.to_dict() if note else None,
                    "previous": neighbors[index - 1] if index > 0 else None,
                    "next": neighbors[index + 1] if index + 1 < len(neighbors) else None,
                }
        for note in notebook.notes:
            if note.id == item_id:
                highlight = next(
                    (h for h in notebook.highlights if h.id == note.highlight_id),
                    None,
                )
                return {
                    "kind": "note",
                    "item": note.to_dict(),
                    "highlight": highlight.to_dict() if highlight else None,
                }
        for node in notebook.mindmap:
            if node.id == item_id:
                return {"kind": "mindmap", "item": node.to_dict()}
        raise AdapterError(f"Item {item_id!r} was not found in the notebook.")

    def list_documents(self) -> list[dict[str, Any]]:
        return [item.to_dict() for item in self.load().documents]

    def read_highlights(
        self,
        document_id: str = "",
        *,
        page_from: int | None = None,
        page_to: int | None = None,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        notebook = self.load()
        wanted = (document_id or "").strip().lower()
        rows: list[dict[str, Any]] = []
        for highlight in notebook.highlights:
            if wanted and wanted not in {
                highlight.document_id.lower(),
                highlight.document_name.lower(),
            }:
                continue
            if page_from is not None and (highlight.page is None or highlight.page < page_from):
                continue
            if page_to is not None and (highlight.page is None or highlight.page > page_to):
                continue
            payload = highlight.to_dict()
            note = next((n for n in notebook.notes if n.id == highlight.note_id), None)
            if note:
                payload["note"] = note.text
            rows.append(payload)
            if len(rows) >= limit:
                break
        return rows

    def mindmap(self, node_id: str = "", *, depth: int = 3) -> dict[str, Any]:
        notebook = self.load()
        by_id = {node.id: node for node in notebook.mindmap}
        if not by_id:
            return {"nodes": [], "root_ids": []}
        start_ids = [node_id] if node_id and node_id in by_id else [
            node.id for node in notebook.mindmap if not node.parent_id
        ]
        if node_id and node_id not in by_id:
            raise AdapterError(f"Mind-map node {node_id!r} was not found.")
        kept: list[MindMapNode] = []
        seen: set[str] = set()

        def walk(current_id: str, remaining: int) -> None:
            if current_id in seen or remaining < 0:
                return
            node = by_id.get(current_id)
            if node is None:
                return
            seen.add(current_id)
            kept.append(node)
            if remaining == 0:
                return
            for child_id in node.children:
                walk(child_id, remaining - 1)

        for start in start_ids:
            walk(start, max(depth, 0))
        return {
            "root_ids": start_ids,
            "nodes": [node.to_dict() for node in kept],
        }

    def tags(self, limit: int = 200) -> list[dict[str, Any]]:
        notebook = self.load()
        counts: dict[str, int] = {}
        for item in (*notebook.highlights, *notebook.notes):
            for tag in item.tags:
                counts[tag] = counts.get(tag, 0) + 1
        ranked = sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))
        return [{"tag": tag, "count": count} for tag, count in ranked[:limit]]

    @property
    def warnings(self) -> list[ParseWarning]:
        self.load()
        return list(self._warnings)

    @property
    def source_file_count(self) -> int:
        return len(self.source_signature())

    @property
    def content_hash(self) -> str:
        raw = "|".join(f"{rel}:{mtime}:{size}" for rel, mtime, size in self.source_signature())
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:24]

    @property
    def cursor(self) -> str:
        return self.content_hash

    def source_signature(self) -> tuple[tuple[str, int, int], ...]:
        return self._scan_signature()

    def capabilities(self) -> AdapterCapabilities:
        writable = self._writeback_available()
        return AdapterCapabilities(
            adapter="export",
            can_read=True,
            can_watch=True,
            official_write=False,
            write_verified=False,
            write_mode=WRITE_MODE_IMPORT_QUEUE,
            write_block_reason=(
                "Official MN4 write APIs are not verified; notes stay in the import queue."
                if writable
                else "Writeback folder is not writable."
            ),
        )

    def diagnose(self) -> AdapterDiagnostics:
        notebook = self.load()
        caps = self.capabilities()
        has_content = bool(
            notebook.documents or notebook.highlights or notebook.notes or notebook.mindmap
        )
        error = ""
        status = "ready"
        recover: list[str] = []
        if not has_content:
            error = "No readable MarginNote documents, highlights, notes or mind maps."
            status = "requires_user_action"
            recover.append("export_markdown_opml")
        if any(item.code == "unreadable" for item in self._warnings):
            status = "degraded"
            recover.append("fix_permissions")
        writeback_available = self._writeback_available()
        if not writeback_available:
            recover.append("choose_writeback_folder")
        return AdapterDiagnostics(
            compatible=has_content,
            adapter="export",
            export_format="markdown-opml",
            file_count=self.source_file_count,
            document_count=len(notebook.documents),
            highlight_count=len(notebook.highlights),
            note_count=len(notebook.notes),
            mindmap_count=len(notebook.mindmap),
            writeback_available=writeback_available,
            cursor=self.cursor,
            content_hash=self.content_hash,
            capabilities=caps,
            warnings=list(self._warnings),
            recover_actions=list(dict.fromkeys(recover)),
            status_hint=status,
            notebook_name=display_name_for(str(self._root)),
            error=error,
        )

    def create_note(
        self,
        rel_path: str,
        content: str,
        frontmatter: dict[str, Any] | None = None,
    ) -> str:
        rel_path = (rel_path or "").strip()
        if not rel_path:
            raise AdapterError("create_note needs a non-empty path.")
        path = _safe_join(self._write_root, _with_md_suffix(rel_path))
        if path.exists():
            raise AdapterError(
                f"Note {_with_md_suffix(rel_path)!r} already exists; use append instead."
            )
        path.parent.mkdir(parents=True, exist_ok=True)
        meta = {"source": "marginnote", "created_by": "deeptutor"}
        meta.update(frontmatter or {})
        path.write_text(_compose_note(meta, content or ""), encoding="utf-8")
        return _rel(self._write_root, path)

    def append_note(self, ref: str, content: str) -> str:
        path = self._resolve_write_note(ref)
        existing = path.read_text(encoding="utf-8")
        separator = "" if existing.endswith("\n") or not existing else "\n"
        path.write_text(existing + separator + (content or ""), encoding="utf-8")
        return _rel(self._write_root, path)

    def create_summary(
        self,
        scope: str,
        analysis: str,
        *,
        frontmatter: dict[str, Any] | None = None,
    ) -> str:
        scope = (scope or "notebook").strip() or "notebook"
        slug = re.sub(r"[^A-Za-z0-9._/-]+", "-", scope).strip("-") or "notebook"
        rel = f"summaries/{slug}.md"
        meta = {
            "source": "marginnote",
            "created_by": "deeptutor",
            "kind": "summary",
            "scope": scope,
        }
        meta.update(frontmatter or {})
        body = analysis or ""
        path = _safe_join(self._write_root, rel)
        if path.exists():
            existing_front, existing_body = split_frontmatter(path.read_text(encoding="utf-8"))
            existing_front.update(meta)
            path.write_text(
                _compose_note(existing_front, existing_body.rstrip() + "\n\n" + body),
                encoding="utf-8",
            )
            return _rel(self._write_root, path)
        return self.create_note(rel, body, frontmatter=meta)

    # --- internals ----------------------------------------------------------

    def _writeback_available(self) -> bool:
        root = self._write_root
        try:
            if root.exists():
                return root.is_dir() and os.access(root, os.W_OK)
            parent = root.parent
            return parent.is_dir() and os.access(parent, os.W_OK)
        except OSError:
            return False

    def _scan_signature(self) -> tuple[tuple[str, int, int], ...]:
        rows: list[tuple[str, int, int]] = []
        for path in self._iter_source_files():
            stat = path.stat()
            rows.append((_rel(self._root, path), int(stat.st_mtime_ns), stat.st_size))
        return tuple(rows)

    def _iter_source_files(self):
        for path in sorted(self._root.rglob("*")):
            if not path.is_file():
                continue
            if _is_ignored(path.relative_to(self._root)):
                continue
            if path.suffix.lower() in {".md", ".markdown", ".opml", ".xml"}:
                yield path

    def _parse(self) -> Notebook:
        highlights: list[Highlight] = []
        notes: list[Note] = []
        mindmap: list[MindMapNode] = []
        documents: dict[str, DocumentInfo] = {}
        self._warnings = []
        for path in self._iter_source_files():
            suffix = path.suffix.lower()
            rel = _rel(self._root, path)
            try:
                if path.stat().st_size == 0:
                    self._warnings.append(ParseWarning(rel, "empty_file", "File is empty."))
                    continue
            except OSError as exc:
                self._warnings.append(
                    ParseWarning(rel, "unreadable", f"Could not stat file: {exc}")
                )
                continue
            try:
                if suffix in {".md", ".markdown"}:
                    file_highlights, file_notes, document = self._parse_markdown(path)
                    highlights.extend(file_highlights)
                    notes.extend(file_notes)
                    documents[document.id] = document
                elif suffix in {".opml", ".xml"}:
                    mindmap.extend(self._parse_opml(path))
            except OSError as exc:
                self._warnings.append(
                    ParseWarning(rel, "unreadable", f"Could not read file: {exc}")
                )
        if not documents and mindmap:
            for node in mindmap:
                if node.parent_id:
                    continue
                documents[node.id] = DocumentInfo(
                    id=node.id, name=node.title, source_path=""
                )
        counts_h: dict[str, int] = {}
        counts_n: dict[str, int] = {}
        for highlight in highlights:
            counts_h[highlight.document_id] = counts_h.get(highlight.document_id, 0) + 1
        for note in notes:
            counts_n[note.document_id] = counts_n.get(note.document_id, 0) + 1
        doc_list = []
        for document in documents.values():
            doc_list.append(
                replace(
                    document,
                    highlight_count=counts_h.get(document.id, 0),
                    note_count=counts_n.get(document.id, 0),
                )
            )
        return Notebook(
            name=self._root.name,
            root=str(self._root),
            documents=doc_list,
            highlights=highlights,
            notes=notes,
            mindmap=mindmap,
        )

    def _parse_markdown(self, path: Path) -> tuple[list[Highlight], list[Note], DocumentInfo]:
        raw = path.read_bytes()
        text = raw.decode("utf-8", errors="replace")
        rel = _rel(self._root, path)
        if "\ufffd" in text:
            self._warnings.append(
                ParseWarning(rel, "encoding", "File is not valid UTF-8; replacement characters were used.")
            )
        if _IMAGE_RE.search(text):
            self._warnings.append(
                ParseWarning(rel, "image_not_extracted", "Embedded images are kept as Markdown links, not extracted.")
            )
        _front, body = split_frontmatter(text)
        if not body.strip():
            self._warnings.append(ParseWarning(rel, "empty_file", "Markdown file has no body."))
        document_id = rel
        document_name = path.stem
        highlights: list[Highlight] = []
        notes: list[Note] = []
        section = ""
        pending_quote: list[str] = []

        def flush_quote() -> Highlight | None:
            if not pending_quote:
                return None
            raw = " ".join(pending_quote).strip()
            pending_quote.clear()
            if not raw:
                return None
            highlight = Highlight(
                id=_stable_id("h", rel, raw),
                document_id=document_id,
                document_name=document_name,
                text=_strip_markup(raw),
                page=_extract_page(raw),
                color=_extract_color(raw),
                tags=_extract_tags(raw),
                section=section,
                source_path=rel,
            )
            highlights.append(highlight)
            return highlight

        last_highlight: Highlight | None = None
        for line in body.splitlines():
            stripped = line.strip()
            if stripped.startswith("#"):
                flush_quote()
                section = stripped.lstrip("#").strip()
                last_highlight = None
                continue
            if stripped.startswith(">"):
                pending_quote.append(stripped.lstrip(">").strip())
                continue
            if pending_quote:
                last_highlight = flush_quote()
            if not stripped:
                continue
            note = Note(
                id=_stable_id("n", rel, stripped),
                document_id=document_id,
                document_name=document_name,
                text=_strip_markup(stripped),
                highlight_id=last_highlight.id if last_highlight else "",
                tags=_extract_tags(stripped),
                page=_extract_page(stripped) or (last_highlight.page if last_highlight else None),
                section=section,
                source_path=rel,
            )
            notes.append(note)
            if last_highlight and not last_highlight.note_id:
                last_highlight.note_id = note.id
                if note.tags:
                    merged = list(dict.fromkeys([*last_highlight.tags, *note.tags]))
                    last_highlight.tags = merged
        flush_quote()
        return (
            highlights,
            notes,
            DocumentInfo(id=document_id, name=document_name, source_path=rel),
        )

    def _parse_opml(self, path: Path) -> list[MindMapNode]:
        rel = _rel(self._root, path)
        try:
            tree = ET.parse(path)
        except ET.ParseError as exc:
            self._warnings.append(
                ParseWarning(rel, "corrupt_opml", f"OPML/XML could not be parsed: {exc}")
            )
            return []
        except OSError as exc:
            self._warnings.append(
                ParseWarning(rel, "unreadable", f"Could not read OPML: {exc}")
            )
            return []
        nodes: list[MindMapNode] = []

        def walk(element: ET.Element, parent_id: str) -> None:
            if element.tag.lower() != "outline":
                for child in list(element):
                    walk(child, parent_id)
                return
            title = (
                element.attrib.get("text")
                or element.attrib.get("title")
                or ""
            ).strip()
            note = (element.attrib.get("_note") or element.attrib.get("note") or "").strip()
            node_id = _stable_id("m", _rel(self._root, path), parent_id, title, note)
            children_ids: list[str] = []
            # Pre-compute child ids so the parent can list them.
            child_outlines = [child for child in list(element) if child.tag.lower() == "outline"]
            for child in child_outlines:
                child_title = (
                    child.attrib.get("text") or child.attrib.get("title") or ""
                ).strip()
                child_note = (
                    child.attrib.get("_note") or child.attrib.get("note") or ""
                ).strip()
                children_ids.append(
                    _stable_id("m", _rel(self._root, path), node_id, child_title, child_note)
                )
            nodes.append(
                MindMapNode(
                    id=node_id,
                    title=title or "(untitled)",
                    parent_id=parent_id,
                    children=children_ids,
                    note=note,
                )
            )
            for child in child_outlines:
                walk(child, node_id)

        root = tree.getroot()
        body = root.find("body")
        start = body if body is not None else root
        for child in list(start):
            walk(child, "")
        return nodes

    def _resolve_write_note(self, ref: str) -> Path:
        ref = (ref or "").strip()
        if not ref:
            raise AdapterError("append_note needs a note path.")
        candidate = _safe_join(self._write_root, _with_md_suffix(ref))
        if candidate.is_file():
            return candidate
        stem = Path(ref).stem.lower()
        if self._write_root.is_dir():
            for path in self._write_root.rglob("*.md"):
                if path.stem.lower() == stem:
                    return path
        raise AdapterError(f"Note {ref!r} was not found; create it first.")


__all__ = ["ExportAdapter", "WRITEBACK_DIRNAME"]
