"""Probing and resolving externally-linked knowledge bases.

A *linked* KB points at a self-contained engine index the user built elsewhere.
These tests cover the three load-bearing pieces: the storage-dir seam
(:func:`resolve_kb_dir`), the connect-time probe (ready index? right engine?
compatible embedding?), and the optional path-jail guard.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from deeptutor.services.rag import embedding_signature as emb_sig
from deeptutor.services.rag.index_versioning import EmbeddingSignature
from deeptutor.services.rag.kb_paths import resolve_kb_dir
from deeptutor.services.rag.linked_kb import (
    LINK_ROOTS_ENV,
    EmbeddingCompat,
    ProbeResult,
    allowed_link_roots,
    assert_path_allowed,
    probe_linked_folder,
    provider_is_linkable,
)

_SIG = EmbeddingSignature(
    binding="openai", model="text-embedding-3-small", dimension=1536, base_url="u", api_version=""
)


def _write_llamaindex_index(root: Path, *, signature: str, docs: int = 0) -> None:
    version = root / "version-1"
    version.mkdir(parents=True)
    (version / "docstore.json").write_text(
        json.dumps({"docstore/data": {f"doc{i}": {} for i in range(docs)}}),
        encoding="utf-8",
    )
    (version / "index_store.json").write_text("{}", encoding="utf-8")
    (version / "meta.json").write_text(
        json.dumps(
            {
                "version": "version-1",
                "signature": signature,
                "layout": "flat",
                "embedding_model": _SIG.model,
            }
        ),
        encoding="utf-8",
    )
    if docs:
        raw = root / "raw"
        raw.mkdir()
        for i in range(docs):
            (raw / f"doc{i}.md").write_text("x", encoding="utf-8")


def _write_graphrag_index(
    root: Path,
    *,
    embedding_signature: str | None = None,
    embedding_model: str | None = None,
    ready: bool = True,
) -> None:
    version = root / "version-1"
    version.mkdir(parents=True)
    if ready:
        (version / "output").mkdir()
        (version / "output" / "entities.parquet").write_bytes(b"parquet")
    meta: dict[str, object] = {"version": "version-1", "provider": "graphrag"}
    if embedding_signature is not None:
        meta["embedding_signature"] = embedding_signature
    if embedding_model is not None:
        meta["embedding_model"] = embedding_model
    (version / "meta.json").write_text(json.dumps(meta), encoding="utf-8")


def test_provider_is_linkable_excludes_pageindex() -> None:
    assert provider_is_linkable("llamaindex")
    assert provider_is_linkable("graphrag")
    assert provider_is_linkable("lightrag")
    assert not provider_is_linkable("pageindex")


def test_resolve_kb_dir_points_at_external_for_linked(tmp_path: Path) -> None:
    base = tmp_path / "kbs"
    base.mkdir()
    external = tmp_path / "external_kb"
    external.mkdir()
    (base / "kb_config.json").write_text(
        json.dumps(
            {
                "knowledge_bases": {
                    "linked": {"type": "linked", "external_path": str(external)},
                    "plain": {"path": "plain"},
                }
            }
        ),
        encoding="utf-8",
    )
    assert resolve_kb_dir(str(base), "linked") == external
    assert resolve_kb_dir(str(base), "plain") == base / "plain"
    # Unknown KB falls back to the conventional layout.
    assert resolve_kb_dir(str(base), "missing") == base / "missing"


def test_probe_rejects_pageindex(tmp_path: Path) -> None:
    result = probe_linked_folder(str(tmp_path), "pageindex")
    assert not result.ok
    assert result.error and "cloud" in result.error.lower()


def test_probe_errors_when_no_index(tmp_path: Path) -> None:
    result = probe_linked_folder(str(tmp_path), "llamaindex")
    assert not result.ok
    assert result.error


def test_probe_finds_ready_llamaindex_index(tmp_path: Path, monkeypatch) -> None:
    _write_llamaindex_index(tmp_path, signature=_SIG.hash(), docs=3)
    # Current embedding matches what the index was built with.
    monkeypatch.setattr(emb_sig, "signature_from_embedding_config", lambda: _SIG)

    result = probe_linked_folder(str(tmp_path), "llamaindex")
    assert result.ok
    assert result.version == "version-1"
    assert result.doc_count == 3
    assert result.embedding.compatible is True
    assert result.warnings == []


def test_probe_warns_on_embedding_mismatch(tmp_path: Path, monkeypatch) -> None:
    _write_llamaindex_index(tmp_path, signature="0000different0000")
    monkeypatch.setattr(emb_sig, "signature_from_embedding_config", lambda: _SIG)

    result = probe_linked_folder(str(tmp_path), "llamaindex")
    # A mismatch is a warning, not a hard block — the user may switch models.
    assert result.ok
    assert result.embedding.compatible is False
    assert result.warnings


def test_probe_unverifiable_embedding_is_a_warning(tmp_path: Path, monkeypatch) -> None:
    _write_llamaindex_index(tmp_path, signature=_SIG.hash())
    # No embedding configured → can't verify compatibility.
    monkeypatch.setattr(emb_sig, "signature_from_embedding_config", lambda: None)

    result = probe_linked_folder(str(tmp_path), "llamaindex")
    assert result.ok
    assert result.embedding.compatible is None
    assert result.warnings


def test_probe_rejects_wrong_engine(tmp_path: Path) -> None:
    # A llamaindex-style index (docstore.json) probed as lightrag should fail:
    # lightrag's ready-marker globs won't match, so no ready version is found.
    _write_llamaindex_index(tmp_path, signature=_SIG.hash())
    result = probe_linked_folder(str(tmp_path), "lightrag")
    assert not result.ok


def test_assert_path_allowed_default_permissive(tmp_path: Path) -> None:
    folder = tmp_path / "vault"
    folder.mkdir()
    assert assert_path_allowed(str(folder)) == folder.resolve()


def test_assert_path_allowed_rejects_missing(tmp_path: Path) -> None:
    with pytest.raises(ValueError):
        assert_path_allowed(str(tmp_path / "nope"))


def test_assert_path_allowed_enforces_allowlist(tmp_path: Path, monkeypatch) -> None:
    allowed = tmp_path / "allowed"
    allowed.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    monkeypatch.setenv("DEEPTUTOR_LINKED_FOLDER_ROOTS", str(allowed))

    inside = allowed / "kb"
    inside.mkdir()
    assert assert_path_allowed(str(inside)) == inside.resolve()
    with pytest.raises(ValueError):
        assert_path_allowed(str(outside))


# --- allowed_link_roots parsing contract -------------------------------------


def test_allowed_link_roots_empty_when_unset_or_blank(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.delenv(LINK_ROOTS_ENV, raising=False)
    assert allowed_link_roots() == []

    monkeypatch.setenv(LINK_ROOTS_ENV, "   ")
    assert allowed_link_roots() == []


def test_allowed_link_roots_parses_pathsep_and_skips_blank_chunks(
    tmp_path: Path, monkeypatch
) -> None:
    first = tmp_path / "first"
    second = tmp_path / "second"
    first.mkdir()
    second.mkdir()
    raw = os.pathsep.join(["", f"  {first}  ", "   ", str(second), ""])
    monkeypatch.setenv(LINK_ROOTS_ENV, raw)

    assert allowed_link_roots() == [first.resolve(), second.resolve()]


def test_allowed_link_roots_expands_and_resolves_user_paths(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv(LINK_ROOTS_ENV, "~/linked-roots")

    assert allowed_link_roots() == [(tmp_path / "linked-roots").resolve()]


# --- provider_is_linkable normalization contract ------------------------------


def test_provider_is_linkable_normalizes_case_and_unknown_fallback() -> None:
    # Name matching is case/space-insensitive.
    assert provider_is_linkable("  LLamaIndex ")
    assert provider_is_linkable("LightRAG")
    # Other engines that are known but not mountable stay excluded.
    assert not provider_is_linkable("pageindex-oss")
    assert not provider_is_linkable("lightrag-server")
    # Unknown names fall back to the default engine, which is linkable.
    assert provider_is_linkable("totally-bogus")


# --- ProbeResult / EmbeddingCompat dataclass contract -------------------------


def test_probe_result_defaults_and_to_dict_shape() -> None:
    result = ProbeResult(provider="llamaindex", external_path="/some/folder")

    assert result.ok is False
    assert result.version is None
    assert result.doc_count is None
    assert result.warnings == []
    assert result.error is None
    assert result.embedding == EmbeddingCompat(
        compatible=None, index_model=None, current_model=None
    )

    data = result.to_dict()
    assert isinstance(data, dict)
    assert data["provider"] == "llamaindex"
    assert data["external_path"] == "/some/folder"
    assert isinstance(data["embedding"], dict)
    assert data["embedding"]["compatible"] is None
    # to_dict is JSON-friendly: no nested dataclass instances remain.
    assert all(not hasattr(value, "to_dict") for value in data.values())


# --- probe_linked_folder rejection and degradation paths ----------------------


def test_probe_rejects_missing_folder(tmp_path: Path) -> None:
    result = probe_linked_folder(str(tmp_path / "nope"), "llamaindex")
    assert not result.ok
    assert result.error and "does not exist" in result.error.lower()


def test_probe_rejects_file_path(tmp_path: Path) -> None:
    file_path = tmp_path / "a-file.txt"
    file_path.write_text("x", encoding="utf-8")

    result = probe_linked_folder(str(file_path), "llamaindex")
    assert not result.ok
    assert result.error and "not a directory" in result.error.lower()


def test_probe_rejects_non_mountable_known_provider(tmp_path: Path) -> None:
    result = probe_linked_folder(str(tmp_path), "pageindex-oss")
    assert not result.ok
    assert result.error and "does not support linking" in result.error


def test_probe_unknown_provider_falls_back_to_default_engine(tmp_path: Path, monkeypatch) -> None:
    _write_llamaindex_index(tmp_path, signature=_SIG.hash())
    monkeypatch.setattr(emb_sig, "signature_from_embedding_config", lambda: _SIG)

    result = probe_linked_folder(str(tmp_path), "totally-bogus")
    # Unknown names normalize to the default engine, so a llamaindex index is
    # found and the result reports the normalized provider.
    assert result.ok
    assert result.provider == "llamaindex"
    assert result.embedding.compatible is True


def test_probe_empty_signature_warns_unverifiable(tmp_path: Path, monkeypatch) -> None:
    version = tmp_path / "version-1"
    version.mkdir()
    (version / "docstore.json").write_text("{}", encoding="utf-8")
    (version / "index_store.json").write_text("{}", encoding="utf-8")
    (version / "meta.json").write_text(
        json.dumps({"version": "version-1", "signature": "", "layout": "flat"}),
        encoding="utf-8",
    )
    monkeypatch.setattr(emb_sig, "signature_from_embedding_config", lambda: _SIG)

    result = probe_linked_folder(str(tmp_path), "llamaindex")
    assert result.ok
    assert result.embedding.compatible is None
    assert result.warnings and "does not record" in result.warnings[0]


def test_probe_graphrag_embedding_signature_match_and_mismatch(tmp_path: Path, monkeypatch) -> None:
    # GraphRAG stamps its embedding identity in ``embedding_signature``, not
    # the LlamaIndex ``signature`` field — the probe must read the right one.
    matching = tmp_path / "matching"
    matching.mkdir()
    _write_graphrag_index(matching, embedding_signature=_SIG.hash(), embedding_model=_SIG.model)
    monkeypatch.setattr(emb_sig, "signature_from_embedding_config", lambda: _SIG)

    result = probe_linked_folder(str(matching), "graphrag")
    assert result.ok
    assert result.embedding.compatible is True
    assert result.embedding.index_model == _SIG.model
    assert result.warnings == []

    mismatched = tmp_path / "mismatched"
    mismatched.mkdir()
    _write_graphrag_index(mismatched, embedding_signature="ffff0000", embedding_model="old-model")

    result = probe_linked_folder(str(mismatched), "graphrag")
    assert result.ok  # mismatch warns, does not block
    assert result.embedding.compatible is False
    assert result.warnings and "old-model" in result.warnings[0]


def test_probe_graphrag_failure_summary_surfaces(tmp_path: Path) -> None:
    _write_graphrag_index(tmp_path, ready=False)

    result = probe_linked_folder(str(tmp_path), "graphrag")
    assert not result.ok
    # The provider's own failure summary is preferred over the generic message.
    assert result.error and "parquet" in result.error.lower()


def test_probe_doc_count_falls_back_to_raw_scan(tmp_path: Path, monkeypatch) -> None:
    # GraphRAG probes carry no doc_count, so the probe counts files under raw/.
    folder = tmp_path / "with-raw"
    folder.mkdir()
    _write_graphrag_index(folder, embedding_signature=_SIG.hash())
    monkeypatch.setattr(emb_sig, "signature_from_embedding_config", lambda: _SIG)
    raw = folder / "raw"
    raw.mkdir()
    (raw / "a.md").write_text("x", encoding="utf-8")
    nested = raw / "sub"
    nested.mkdir()
    (nested / "b.md").write_text("x", encoding="utf-8")

    result = probe_linked_folder(str(folder), "graphrag")
    assert result.ok
    assert result.doc_count == 2

    empty = tmp_path / "without-raw"
    empty.mkdir()
    _write_graphrag_index(empty, embedding_signature=_SIG.hash())
    result = probe_linked_folder(str(empty), "graphrag")
    assert result.ok
    assert result.doc_count is None


def test_probe_unpublished_building_candidate_not_ready(tmp_path: Path) -> None:
    version = tmp_path / "version-1"
    version.mkdir()
    (version / "docstore.json").write_text("{}", encoding="utf-8")
    (version / "index_store.json").write_text("{}", encoding="utf-8")
    (version / ".building.json").write_text("{}", encoding="utf-8")
    (version / "meta.json").write_text(
        json.dumps({"version": "version-1", "signature": _SIG.hash(), "layout": "flat"}),
        encoding="utf-8",
    )

    result = probe_linked_folder(str(tmp_path), "llamaindex")
    assert not result.ok
    assert result.error and "persistence verification" in result.error.lower()


# --- assert_path_allowed boundary contract ------------------------------------


def test_assert_path_allowed_rejects_file(tmp_path: Path) -> None:
    file_path = tmp_path / "a-file.txt"
    file_path.write_text("x", encoding="utf-8")
    with pytest.raises(ValueError, match="Not a directory"):
        assert_path_allowed(str(file_path))


def test_assert_path_allowed_allows_root_itself(tmp_path: Path, monkeypatch) -> None:
    root = tmp_path / "vault"
    root.mkdir()
    monkeypatch.setenv("DEEPTUTOR_LINKED_FOLDER_ROOTS", str(root))

    assert assert_path_allowed(str(root)) == root.resolve()


def test_assert_path_allowed_accepts_any_configured_root(tmp_path: Path, monkeypatch) -> None:
    first = tmp_path / "first"
    second = tmp_path / "second"
    first.mkdir()
    second.mkdir()
    # Blank chunks between roots are tolerated.
    monkeypatch.setenv(
        "DEEPTUTOR_LINKED_FOLDER_ROOTS",
        os.pathsep.join(["", str(first), "", str(second)]),
    )

    under_second = second / "kb"
    under_second.mkdir()
    assert assert_path_allowed(str(under_second)) == under_second.resolve()


def test_assert_path_allowed_rejects_symlink_escape(tmp_path: Path, monkeypatch) -> None:
    allowed = tmp_path / "allowed"
    allowed.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "secret.txt").write_text("x", encoding="utf-8")
    tunnel = allowed / "kb"
    tunnel.symlink_to(outside, target_is_directory=True)
    monkeypatch.setenv("DEEPTUTOR_LINKED_FOLDER_ROOTS", str(allowed))

    # The symlink resolves before the allowlist check, so it cannot be used to
    # reach a folder outside the configured roots.
    with pytest.raises(ValueError, match="outside the locations"):
        assert_path_allowed(str(tunnel))


def test_assert_path_allowed_expands_user_home(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("HOME", str(tmp_path))
    folder = tmp_path / "linked_kb"
    folder.mkdir()

    assert assert_path_allowed("~/linked_kb") == folder.resolve()
