"""Regression tests for the ``utc_now_iso_z`` timestamp helper.

The five historical call sites (PageIndex/LightRAG/GraphRAG meta.json,
``index_versioning`` version meta, parsing cache manifest) used the inline
``datetime.now(timezone.utc).replace(tzinfo=None).isoformat() + "Z"`` stamp.
They now share ``deeptutor.utils.time_utils.utc_now_iso_z``; these tests pin
a fixed instant and assert each call site's persisted stamp stays
byte-identical to the legacy inline expression.
"""

from __future__ import annotations

from datetime import datetime, timezone
import json
from pathlib import Path

import pytest

from deeptutor.utils import time_utils

FIXED = datetime(2026, 3, 4, 5, 6, 7, 891011, tzinfo=timezone.utc)
LEGACY_STAMP = FIXED.replace(tzinfo=None).isoformat() + "Z"


class _FixedDatetime(datetime):
    @classmethod
    def now(cls, tz=None):  # type: ignore[override]
        return FIXED if tz is not None else FIXED.replace(tzinfo=None)


@pytest.fixture(autouse=True)
def _freeze_utc_now(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(time_utils, "datetime", _FixedDatetime)


def _legacy(instant: datetime) -> str:
    return instant.replace(tzinfo=None).isoformat() + "Z"


@pytest.mark.parametrize(
    "instant",
    [
        FIXED,
        datetime(2026, 3, 4, 5, 6, 7, 0, tzinfo=timezone.utc),
    ],
    ids=["with-microseconds", "zero-microseconds"],
)
def test_helper_matches_legacy_expression(monkeypatch: pytest.MonkeyPatch, instant) -> None:
    class _Pinned(datetime):
        @classmethod
        def now(cls, tz=None):  # type: ignore[override]
            return instant if tz is not None else instant.replace(tzinfo=None)

    monkeypatch.setattr(time_utils, "datetime", _Pinned)
    assert time_utils.utc_now_iso_z() == _legacy(instant)


def test_pageindex_meta_stamp_matches_legacy(tmp_path: Path) -> None:
    from deeptutor.services.rag.pipelines.pageindex import storage

    storage.write_meta(tmp_path / "version-1")
    meta = json.loads((tmp_path / "version-1" / storage.META_FILENAME).read_text(encoding="utf-8"))
    assert meta["created_at"] == LEGACY_STAMP


def test_lightrag_meta_stamp_matches_legacy(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from deeptutor.services.rag.pipelines.lightrag import engine, storage

    monkeypatch.setattr(engine, "installed_version", lambda: "1.5.7")
    storage.write_meta(tmp_path / "version-1")
    meta = json.loads((tmp_path / "version-1" / storage.META_FILENAME).read_text(encoding="utf-8"))
    assert meta["created_at"] == LEGACY_STAMP
    assert meta["updated_at"] == LEGACY_STAMP


def test_index_versioning_meta_stamp_matches_legacy(tmp_path: Path) -> None:
    from deeptutor.services.rag.index_versioning import EmbeddingSignature, write_version_meta

    signature = EmbeddingSignature(
        binding="openai",
        model="text-embedding-3-small",
        dimension=1536,
        base_url="https://example.test/v1",
        api_version="",
    )
    write_version_meta(tmp_path, signature, storage_dir=tmp_path / "version-1")
    meta = json.loads((tmp_path / "version-1" / "meta.json").read_text(encoding="utf-8"))
    assert meta["created_at"] == LEGACY_STAMP


def test_graphrag_meta_stamp_matches_legacy(tmp_path: Path) -> None:
    from deeptutor.services.rag.pipelines.graphrag import storage

    storage.write_meta(tmp_path / "version-1")
    meta = json.loads((tmp_path / "version-1" / storage.META_FILENAME).read_text(encoding="utf-8"))
    assert meta["created_at"] == LEGACY_STAMP


def test_parsing_cache_manifest_stamp_matches_legacy(tmp_path: Path) -> None:
    from deeptutor.services.parsing import cache

    cache.write_manifest(tmp_path, {"source": "doc.pdf"})
    manifest = json.loads((tmp_path / cache.MANIFEST_FILENAME).read_text(encoding="utf-8"))
    assert manifest["created_at"] == LEGACY_STAMP
    assert manifest["source"] == "doc.pdf"
