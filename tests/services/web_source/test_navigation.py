"""Tests for web-source navigation tree assembly.

Covers ``flat_to_tree`` hierarchical assembly (orphan links, depth
oscillation, missing-field defaults) and the ``build_navigation_manifest``
sort/dedup contract. Pure functions — no I/O, fully offline.
"""

from __future__ import annotations

import pytest

from deeptutor.services.web_source.navigation import (
    build_navigation_manifest,
    flat_to_tree,
)


def _link(title: str, depth: int, url: str = "") -> dict:
    return {"title": title, "url": url, "depth": depth}


def _shape(nodes: list[dict]) -> list[tuple]:
    """Reduce a tree to (title, children-shape) tuples for comparisons."""
    return [(n["title"], _shape(n["children"])) for n in nodes]


# -- flat_to_tree -------------------------------------------------------


def test_flat_to_tree_empty_input() -> None:
    assert flat_to_tree([], {}) == []


def test_flat_to_tree_chain_nesting() -> None:
    tree = flat_to_tree(
        [
            _link("Getting Started", 0, "/start"),
            _link("Install", 1, "/install"),
            _link("Prerequisites", 2, "/prereq"),
        ],
        {"/start": "start.md", "/install": "install.md", "/prereq": "prereq.md"},
    )
    assert _shape(tree) == [("Getting Started", [("Install", [("Prerequisites", [])])])]
    assert tree[0]["file_path"] == "start.md"
    assert tree[0]["children"][0]["file_path"] == "install.md"
    assert tree[0]["children"][0]["children"][0]["file_path"] == "prereq.md"


@pytest.mark.parametrize(
    ("links", "expected"),
    [
        pytest.param(
            [
                _link("a", 0),
                _link("a1", 1),
                _link("a2", 1),
                _link("b", 0),
                _link("b1", 1),
            ],
            [("a", [("a1", []), ("a2", [])]), ("b", [("b1", [])])],
            id="sibling-groups",
        ),
        pytest.param(
            [_link("only", 0)],
            [("only", [])],
            id="single-root",
        ),
        pytest.param(
            [
                _link("a", 0),
                _link("a1", 1),
                _link("a1x", 2),
                _link("a2", 1),
                _link("b", 0),
            ],
            [("a", [("a1", [("a1x", [])]), ("a2", [])]), ("b", [])],
            id="mixed-depth-return",
        ),
        pytest.param(
            [
                _link("a", 0),
                _link("b", 1),
                _link("c", 0),
                _link("d", 1),
            ],
            [("a", [("b", [])]), ("c", [("d", [])])],
            id="depth-oscillation",
        ),
    ],
)
def test_flat_to_tree_assembly(links: list[dict], expected: list[tuple]) -> None:
    assert _shape(flat_to_tree(links, {})) == expected


def test_flat_to_tree_missing_fields_defaults() -> None:
    tree = flat_to_tree([{}], {})
    node = tree[0]
    assert node["title"] == "Untitled"
    assert node["url"] == ""
    assert node["file_path"] == ""
    assert node["children"] == []
    assert node["id"] == "nav-0"


def test_flat_to_tree_maps_urls_to_files() -> None:
    tree = flat_to_tree(
        [
            _link("known", 0, "/docs/known"),
            _link("unknown", 0, "/docs/unknown"),
        ],
        {"/docs/known": "known.md"},
    )
    assert tree[0]["file_path"] == "known.md"
    assert tree[1]["file_path"] == ""


def test_flat_to_tree_orphan_deep_link_attaches_to_nearest_ancestor() -> None:
    # depth jumps 0 -> 5 -> 1: the orphan depth-5 link must attach to the
    # nearest shallower ancestor (depth-0), and the depth-1 sibling too.
    tree = flat_to_tree(
        [_link("a", 0), _link("deep", 5), _link("child", 1)],
        {},
    )
    assert _shape(tree) == [("a", [("deep", []), ("child", [])])]


def test_flat_to_tree_leading_deep_link_becomes_root() -> None:
    # No ancestor exists yet for the deep first link: it must surface as a
    # root node instead of being dropped.
    tree = flat_to_tree([_link("orphan", 3), _link("root", 0)], {})
    assert _shape(tree) == [("orphan", []), ("root", [])]


def test_flat_to_tree_negative_depth_becomes_root() -> None:
    # A negative depth pops shallower nodes and becomes a root; because no
    # real ancestor is shallower, the next depth-0 link nests beneath it.
    tree = flat_to_tree([_link("a", 0), _link("neg", -1), _link("b", 0)], {})
    assert _shape(tree) == [("a", []), ("neg", [("b", [])])]


def test_flat_to_tree_cycle_input_preserves_all_nodes() -> None:
    # Oscillating depth pattern that repeatedly closes and reopens
    # subtrees: every input link must survive as exactly one node with a
    # unique id assigned in input order.
    links = [_link(f"item{i}", depth) for i, depth in enumerate([0, 1, 2, 0, 1, 2, 1, 0, 1, 0])]
    tree = flat_to_tree(links, {})

    def _collect(nodes: list[dict]) -> list[dict]:
        out: list[dict] = []
        for node in nodes:
            out.append(node)
            out.extend(_collect(node["children"]))
        return out

    flat = _collect(tree)
    assert [n["title"] for n in flat] == [lk["title"] for lk in links]
    assert [n["id"] for n in flat] == [f"nav-{i}" for i in range(len(links))]
    assert len({n["id"] for n in flat}) == len(links)
    assert _shape(tree) == [
        ("item0", [("item1", [("item2", [])])]),
        ("item3", [("item4", [("item5", [])]), ("item6", [])]),
        ("item7", [("item8", [])]),
        ("item9", []),
    ]


def test_flat_to_tree_ids_assign_in_input_order() -> None:
    tree = flat_to_tree(
        [_link("z", 1), _link("y", 0), _link("x", 2)],
        {},
    )
    assert _shape(tree) == [("z", []), ("y", [("x", [])])]
    assert tree[0]["id"] == "nav-0"
    assert tree[1]["id"] == "nav-1"
    assert tree[1]["children"][0]["id"] == "nav-2"


# -- build_navigation_manifest ------------------------------------------


def test_build_navigation_manifest_empty_links() -> None:
    manifest = build_navigation_manifest([], "sidebar", {"page.md": "/page"})
    assert manifest == {"kind": "", "nodes": []}


@pytest.mark.parametrize(
    ("nav_kind", "expected"),
    [
        pytest.param("sidebar", "sidebar", id="explicit-kind-kept"),
        pytest.param("", "inferred", id="empty-kind-inferred"),
        pytest.param(None, "inferred", id="none-kind-inferred"),
    ],
)
def test_build_navigation_manifest_kind(nav_kind: str | None, expected: str) -> None:
    links = [_link("Home", 0, "/home")]
    manifest = build_navigation_manifest(links, nav_kind, {})
    assert manifest["kind"] == expected
    assert manifest["nodes"] != []


def test_build_navigation_manifest_inverts_page_urls() -> None:
    manifest = build_navigation_manifest(
        [_link("Guide", 0, "/docs/guide")],
        "sidebar",
        {"guide.md": "/docs/guide", "other.md": "/docs/other"},
    )
    assert manifest["nodes"][0]["file_path"] == "guide.md"


def test_build_navigation_manifest_duplicate_url_last_filename_wins() -> None:
    # page_urls inversion is a dict comprehension: when two filenames claim
    # the same URL the later entry overwrites the earlier one.
    manifest = build_navigation_manifest(
        [_link("Page", 0, "/docs/page")],
        "sidebar",
        {"old.md": "/docs/page", "new.md": "/docs/page"},
    )
    assert manifest["nodes"][0]["file_path"] == "new.md"


def test_build_navigation_manifest_preserves_link_order() -> None:
    links = [
        _link("third", 0, "/c"),
        _link("first", 1, "/a"),
        _link("second", 1, "/b"),
    ]
    manifest = build_navigation_manifest(links, "sidebar", {})
    titles = [n["title"] for n in manifest["nodes"][0]["children"]]
    assert titles == ["first", "second"]
    assert manifest["nodes"][0]["title"] == "third"


def test_build_navigation_manifest_end_to_end_tree() -> None:
    manifest = build_navigation_manifest(
        [
            _link("Docs", 0, "/docs"),
            _link("Intro", 1, "/docs/intro"),
            _link("Setup", 2, "/docs/setup"),
            _link("API", 0, "/api"),
        ],
        "sidebar",
        {
            "docs.md": "/docs",
            "intro.md": "/docs/intro",
            "setup.md": "/docs/setup",
            "api.md": "/api",
        },
    )
    assert manifest["kind"] == "sidebar"
    assert _shape(manifest["nodes"]) == [
        ("Docs", [("Intro", [("Setup", [])])]),
        ("API", []),
    ]
    file_paths = [
        manifest["nodes"][0]["file_path"],
        manifest["nodes"][0]["children"][0]["file_path"],
        manifest["nodes"][0]["children"][0]["children"][0]["file_path"],
        manifest["nodes"][1]["file_path"],
    ]
    assert file_paths == ["docs.md", "intro.md", "setup.md", "api.md"]
