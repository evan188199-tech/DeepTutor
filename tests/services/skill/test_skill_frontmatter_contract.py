"""Skill frontmatter parsing contract: fence closure, long input, separator ambiguity, field backfill.

Pins the current behaviour of ``SkillService._parse_frontmatter`` (driven by
``_FRONTMATTER_RE`` at ``deeptutor/services/skill/service.py``) and of the
fence gate used by ``_normalize_content``. Every assertion records observed
behaviour; nothing here encodes a future fix.
"""

from __future__ import annotations

import time
from pathlib import Path

import pytest

from deeptutor.services.skill.service import SkillService


@pytest.fixture
def svc(tmp_path: Path) -> SkillService:
    return SkillService(root=tmp_path / "skills", builtin_root=None)


PARSE_CASES = [
    pytest.param(
        "---\nname: x\ndescription: d\n---\nbody",
        {"name": "x", "description": "d"},
        "body",
        id="closed-fence-minimal",
    ),
    pytest.param(
        "---\nname: x\n---\n\n\nbody",
        {"name": "x"},
        "body",
        id="closed-fence-blank-lines-stripped",
    ),
    pytest.param(
        "---\nname: x\n---\n\n    indented code",
        {"name": "x"},
        "indented code",
        id="closed-fence-body-indentation-stripped",
    ),
    pytest.param(
        "---   \nname: x\n---\nbody",
        {"name": "x"},
        "body",
        id="open-fence-trailing-spaces-tolerated",
    ),
    pytest.param(
        "---\n\nname: x\n---\nbody",
        {"name": "x"},
        "body",
        id="blank-line-after-open-fence-tolerated",
    ),
    pytest.param(
        "---\nname: x\nbody text",
        {},
        "---\nname: x\nbody text",
        id="unclosed-fence-content-preserved-whole",
    ),
    pytest.param(
        "---\nname: x\nbody text\n---\n",
        {},
        "",
        id="unclosed-fence-with-later-rule-yaml-error-empty-body",
    ),
    pytest.param(
        "---\n---\nbody",
        {},
        "---\n---\nbody",
        id="empty-fence-no-inner-content-not-frontmatter",
    ),
    pytest.param(
        "just body\nmore",
        {},
        "just body\nmore",
        id="no-leading-fence-content-preserved",
    ),
    pytest.param(
        "---\nname: x\n---\n---\nbody",
        {"name": "x"},
        "---\nbody",
        id="double-fence-extra-rule-stays-in-body",
    ),
    pytest.param(
        "---\n# Title\n---\nbody",
        {},
        "body",
        id="thematic-break-false-positive-middle-dropped",
    ),
    pytest.param(
        "---\n123\n---\nbody",
        {},
        "body",
        id="non-dict-scalar-fence-yields-empty-meta",
    ),
    pytest.param(
        "---\n- a\n- b\n---\nbody",
        {},
        "body",
        id="non-dict-list-fence-yields-empty-meta",
    ),
]


@pytest.mark.parametrize(("content", "expected_meta", "expected_body"), PARSE_CASES)
def test_parse_frontmatter_contract(
    content: str, expected_meta: dict, expected_body: str
) -> None:
    meta, body = SkillService._parse_frontmatter(content)
    assert meta == expected_meta
    assert body == expected_body


NORMALIZE_CASES = [
    pytest.param(
        "slug",
        "Some desc",
        "plain body\nline2",
        ["tool"],
        {"name": "slug", "description": "Some desc", "tags": ["tool"]},
        "plain body\nline2\n",
        id="no-fence-synthesizes-header-with-tags",
    ),
    pytest.param(
        "slug",
        "Some desc",
        "\n\n  padded body",
        None,
        {"name": "slug", "description": "Some desc"},
        "padded body\n",
        id="no-fence-body-leading-whitespace-stripped",
    ),
    pytest.param(
        "slug",
        "Backfilled desc",
        "---\nname: old\ntags: [a]\n---\nbody",
        None,
        {"name": "slug", "tags": ["a"], "description": "Backfilled desc"},
        "body\n",
        id="fence-missing-description-backfilled-name-forced",
    ),
    pytest.param(
        "slug",
        "New desc",
        "---\nname: old\ndescription: old d\ntags: [a]\n---\nbody",
        ["x"],
        {"name": "slug", "description": "New desc", "tags": ["x"]},
        "body\n",
        id="fence-tags-replaced",
    ),
    pytest.param(
        "slug",
        "New desc",
        "---\nname: old\ndescription: old d\ntags: [a]\n---\nbody",
        [],
        {"name": "slug", "description": "New desc"},
        "body\n",
        id="fence-empty-tags-key-dropped",
    ),
    pytest.param(
        "slug",
        "Desc",
        "---\n# Title\n---\nbody",
        None,
        {"name": "slug", "description": "Desc"},
        "body\n",
        id="thematic-break-doc-rewritten-lossy",
    ),
    pytest.param(
        "slug",
        "Desc",
        "---\nname: x\nno closing fence",
        None,
        {"name": "slug", "description": "Desc"},
        "---\nname: x\nno closing fence\n",
        id="unclosed-fence-header-prepended-original-kept",
    ),
    pytest.param(
        "slug",
        "Desc",
        "---\n123\n---\nbody",
        None,
        {"name": "slug", "description": "Desc"},
        "body\n",
        id="non-dict-fence-replaced-with-header",
    ),
    pytest.param(
        "slug",
        "Desc",
        "---\n---\nbody",
        None,
        {"name": "slug", "description": "Desc"},
        "---\n---\nbody\n",
        id="empty-fence-no-inner-header-prepended-original-kept",
    ),
]


@pytest.mark.parametrize(
    ("name", "description", "content", "tags", "expected_meta", "expected_body"),
    NORMALIZE_CASES,
)
def test_normalize_content_backfill_contract(
    svc: SkillService,
    name: str,
    description: str,
    content: str,
    tags: list[str] | None,
    expected_meta: dict,
    expected_body: str,
) -> None:
    out = svc._normalize_content(name, description, content, tags=tags)
    assert out.startswith("---\n")
    meta, body = SkillService._parse_frontmatter(out)
    assert meta == expected_meta
    assert body == expected_body


def test_long_input_closed_fence_body_preserved_verbatim() -> None:
    body_text = "paragraph line\n" * 150_000
    content = f"---\nname: big-skill\ndescription: d\n---\n{body_text}"
    started = time.monotonic()
    meta, body = SkillService._parse_frontmatter(content)
    elapsed = time.monotonic() - started
    assert meta == {"name": "big-skill", "description": "d"}
    assert body == body_text
    assert elapsed < 10.0


def test_long_input_unclosed_fence_content_preserved_whole() -> None:
    body_text = "paragraph line\n" * 150_000
    content = f"---\nname: x\n{body_text}"
    started = time.monotonic()
    meta, body = SkillService._parse_frontmatter(content)
    elapsed = time.monotonic() - started
    assert meta == {}
    assert body == content
    assert elapsed < 10.0


def test_get_detail_unclosed_fence_skill_reads_with_empty_description(
    tmp_path: Path, svc: SkillService
) -> None:
    skill_dir = tmp_path / "skills" / "wip-skill"
    skill_dir.mkdir(parents=True)
    raw = "---\nname: wip-skill\nno closing fence\n"
    (skill_dir / "SKILL.md").write_text(raw, encoding="utf-8")
    info = svc.get_detail("wip-skill")
    assert info.content == raw
    assert info.description == ""


def test_create_on_fenceless_content_round_trips_through_get_detail(
    svc: SkillService,
) -> None:
    svc.create("fmt-skill", "Created from plain body", "just body")
    detail = svc.get_detail("fmt-skill")
    meta, body = SkillService._parse_frontmatter(detail.content)
    assert meta["name"] == "fmt-skill"
    assert meta["description"] == "Created from plain body"
    assert body == "just body\n"
