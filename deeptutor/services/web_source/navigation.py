"""Build and merge navigation trees for web-source KBs."""

from __future__ import annotations

import logging
from typing import Any

from deeptutor.services.web_source.pairing import strip_lang_prefix_from_path

logger = logging.getLogger(__name__)


# -- flat-to-tree conversion -------------------------------------------


def flat_to_tree(
    links: list[dict],
    url_to_file: dict[str, str],
) -> list[dict]:
    """Convert a flat list of navigation links into a nested tree.

    Uses the ``depth`` field to determine nesting.  Links at depth N
    become children of the most recent link at depth N-1.
    """
    result: list[dict] = []
    stack: list[tuple[int, dict]] = []
    counter = 0

    for link in links:
        depth = link.get("depth", 0)
        title = link.get("title", "Untitled")
        url = link.get("url", "")
        file_path = url_to_file.get(url, "")

        node: dict[str, Any] = {
            "id": f"nav-{counter}",
            "title": title,
            "url": url,
            "file_path": file_path,
            "children": [],
        }
        counter += 1

        while stack and stack[-1][0] >= depth:
            stack.pop()

        if stack:
            stack[-1][1]["children"].append(node)
        else:
            result.append(node)

        stack.append((depth, node))

    return result


def build_navigation_manifest(
    nav_links: list[dict],
    nav_kind: str,
    page_urls: dict[str, str],
) -> dict:
    """Build a serializable navigation manifest from crawl output.

    Returns ``{"kind": str, "nodes": [...]}``.
    """
    if not nav_links:
        return {"kind": "", "nodes": []}

    url_to_file: dict[str, str] = {}
    for fname, url in page_urls.items():
        url_to_file[url] = fname

    nodes = flat_to_tree(nav_links, url_to_file)
    return {"kind": nav_kind or "inferred", "nodes": nodes}


def merge_navigation(
    en_nav: dict,
    zh_nav: dict,
    zh_lang_prefix: str,
    pair_key: str,
) -> dict:
    """Merge parallel EN/ZH trees into one English-primary navigation tree."""
    zh_by_base: dict[str, dict] = {}
    _index_zh_nodes(zh_nav.get("nodes", []), zh_lang_prefix, zh_by_base)
    merged_kind = en_nav.get("kind", "inferred")
    if zh_nav.get("kind") == "original":
        merged_kind = "original"
    return {
        "kind": merged_kind,
        "nodes": [_merge_node(node, zh_by_base, pair_key) for node in en_nav.get("nodes", [])],
    }


def _index_zh_nodes(nodes: list[dict], zh_lang_prefix: str, out: dict[str, dict]) -> None:
    for node in nodes:
        file_path = str(node.get("file_path") or "")
        if file_path:
            out[strip_lang_prefix_from_path(file_path, zh_lang_prefix)] = node
        _index_zh_nodes(node.get("children", []), zh_lang_prefix, out)


def _merge_node(en_node: dict, zh_by_base: dict[str, dict], pair_key: str) -> dict:
    en_file_path = str(en_node.get("file_path") or "")
    zh_node = zh_by_base.get(en_file_path)
    page_class = ""
    if en_file_path and zh_node:
        page_class = "bilingual"
    elif en_file_path:
        page_class = "en_only"
    elif zh_node:
        page_class = "zh_only"
    return {
        "id": en_node.get("id", ""),
        "title": en_node.get("title", ""),
        "title_zh": zh_node.get("title", "") if zh_node else "",
        "url": en_node.get("url", ""),
        "file_path": en_file_path,
        "file_path_zh": zh_node.get("file_path", "") if zh_node else "",
        "page_class": page_class,
        "pair_key": pair_key,
        "children": [
            _merge_node(child, zh_by_base, pair_key) for child in en_node.get("children", [])
        ],
    }
