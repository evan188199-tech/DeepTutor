"""Synthetic archives only; no cloud transport and no production parse cache.

Unit contract for the MinerU slice checkpoint store: content-and-config
addressed job directories, atomic save/load round-trips, degraded loads for
corrupt or partially written state, size and symlink guards, and
concurrent-writer safety. The filesystem is redirected to ``tmp_path``.
"""

from __future__ import annotations

import dataclasses
import hashlib
import json
from pathlib import Path
import threading

import pytest

from deeptutor.services.parsing.engines.mineru import checkpoints
from deeptutor.services.parsing.engines.mineru.checkpoints import (
    SliceCheckpoint,
    job_directory,
)
from deeptutor.services.parsing.engines.mineru.config import MinerUConfig

CFG = MinerUConfig(mode="cloud", api_token="tok")


@pytest.fixture()
def cache_root(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    root = tmp_path / "checkpoints"
    monkeypatch.setattr(checkpoints, "checkpoint_root", lambda: root)
    return root


def _source(tmp_path: Path, content: bytes = b"pdf-bytes", name: str = "doc.pdf") -> Path:
    path = tmp_path / name
    path.write_bytes(content)
    return path


def _checkpoint(cache_root: Path) -> SliceCheckpoint:
    return SliceCheckpoint(cache_root / "job", 0, 2)


def _archive_name(payload: bytes) -> str:
    return f"{hashlib.sha256(payload).hexdigest()}.zip"


# ---------------------------------------------------------------------------
# job_directory: content + config addressing
# ---------------------------------------------------------------------------


def test_job_directory_is_stable_hex_under_checkpoint_root(cache_root, tmp_path) -> None:
    directory = job_directory(_source(tmp_path), CFG)
    assert directory.parent == cache_root
    assert len(directory.name) == 64
    assert all(c in "0123456789abcdef" for c in directory.name)
    assert job_directory(_source(tmp_path), CFG) == directory


def test_job_directory_separates_different_source_content(cache_root, tmp_path) -> None:
    first = job_directory(_source(tmp_path, b"one"), CFG)
    second = job_directory(_source(tmp_path, b"two"), CFG)
    assert first != second


def test_job_directory_separates_same_bytes_under_different_names(cache_root, tmp_path) -> None:
    first = job_directory(_source(tmp_path, b"same", name="a.pdf"), CFG)
    second = job_directory(_source(tmp_path, b"same", name="b.pdf"), CFG)
    assert first != second


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("api_base_url", "https://mineru.example.org"),
        ("model_version", "vlm"),
        ("language", "en"),
        ("enable_formula", False),
        ("enable_table", False),
        ("is_ocr", True),
        ("max_pages_per_part", 5),
    ],
)
def test_job_directory_separates_config_knobs(cache_root, tmp_path, field: str, value) -> None:
    base = job_directory(_source(tmp_path), CFG)
    altered = job_directory(_source(tmp_path), dataclasses.replace(CFG, **{field: value}))
    assert base != altered


# ---------------------------------------------------------------------------
# save / load round-trip
# ---------------------------------------------------------------------------


def test_save_then_load_roundtrip_writes_archive_and_pointer(cache_root) -> None:
    checkpoint = _checkpoint(cache_root)
    payload = b"archive-bytes"
    assert not checkpoint.directory.exists()

    checkpoint.save(payload)

    digest = hashlib.sha256(payload).hexdigest()
    assert (checkpoint.directory / f"{digest}.zip").is_file()
    assert json.loads(checkpoint.pointer.read_text(encoding="utf-8")) == {"sha256": digest}
    assert checkpoint.load() == payload


def test_save_leaves_no_temporary_files_behind(cache_root) -> None:
    checkpoint = _checkpoint(cache_root)
    payload = b"payload"
    checkpoint.save(payload)
    checkpoint.save(payload + b"-v2")
    names = {path.name for path in checkpoint.directory.iterdir()}
    assert names == {_archive_name(payload), _archive_name(payload + b"-v2"), "ready.json"}


def test_save_overwrite_moves_pointer_to_latest_archive(cache_root) -> None:
    checkpoint = _checkpoint(cache_root)
    first, second = b"first-archive", b"second-archive"
    checkpoint.save(first)
    checkpoint.save(second)

    assert json.loads(checkpoint.pointer.read_text(encoding="utf-8")) == {
        "sha256": hashlib.sha256(second).hexdigest()
    }
    assert checkpoint.load() == second


def test_save_skips_oversized_payload_entirely(cache_root, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(checkpoints, "_MAX_ARCHIVE_BYTES", 8)
    checkpoint = _checkpoint(cache_root)

    checkpoint.save(b"way-too-large-payload")

    assert not checkpoint.directory.exists()
    assert checkpoint.load() is None


# ---------------------------------------------------------------------------
# load degradation: corrupt, partial, or missing state
# ---------------------------------------------------------------------------


def test_load_without_pointer_returns_none(cache_root) -> None:
    assert _checkpoint(cache_root).load() is None


def test_load_with_pointer_but_missing_archive_returns_none(cache_root) -> None:
    checkpoint = _checkpoint(cache_root)
    checkpoint.directory.mkdir(parents=True)
    payload_digest = hashlib.sha256(b"never-written").hexdigest()
    checkpoint.pointer.write_text(json.dumps({"sha256": payload_digest}), encoding="utf-8")

    assert checkpoint.load() is None


@pytest.mark.parametrize(
    "raw_pointer",
    [
        b'{"sha256": "ab',  # truncated half-write
        b"\xff\xfe\xff",  # invalid utf-8
        b'["sha256"]',  # json array, not an object
        b'{"digest": "x"}',  # missing key
        b'{"sha256": 42}',  # wrong type
        json.dumps({"sha256": "0" * 63}).encode(),  # too short
        json.dumps({"sha256": "0" * 65}).encode(),  # too long
        json.dumps({"sha256": "A" * 64}).encode(),  # uppercase is rejected
        json.dumps({"sha256": "z" * 64}).encode(),  # non-hex
    ],
)
def test_load_degrades_to_none_on_corrupt_pointer(cache_root, tmp_path, raw_pointer: bytes) -> None:
    checkpoint = _checkpoint(cache_root)
    checkpoint.directory.mkdir(parents=True)
    checkpoint.pointer.write_bytes(raw_pointer)
    # A decoy archive named for a valid digest must not rescue a bad pointer.
    decoy = hashlib.sha256(b"decoy").hexdigest()
    (checkpoint.directory / f"{decoy}.zip").write_bytes(b"decoy")

    assert checkpoint.load() is None


def test_load_detects_tampered_archive(cache_root) -> None:
    checkpoint = _checkpoint(cache_root)
    payload = b"original-archive"
    checkpoint.save(payload)
    archive = checkpoint.directory / _archive_name(payload)
    archive.write_bytes(b"tampered-content!")

    assert checkpoint.load() is None


def test_load_rejects_archive_over_size_limit(cache_root, monkeypatch: pytest.MonkeyPatch) -> None:
    checkpoint = _checkpoint(cache_root)
    payload = b"payload"
    checkpoint.save(payload)
    monkeypatch.setattr(checkpoints, "_MAX_ARCHIVE_BYTES", 2)

    assert checkpoint.load() is None


# ---------------------------------------------------------------------------
# load guards: symlinks must never be followed
# ---------------------------------------------------------------------------


def test_load_rejects_symlinked_directory(cache_root, tmp_path) -> None:
    checkpoint = _checkpoint(cache_root)
    checkpoint.save(b"payload")
    external = tmp_path / "elsewhere" / "0-2"
    external.parent.mkdir()
    checkpoint.directory.rename(external)
    checkpoint.directory.symlink_to(external, target_is_directory=True)

    assert checkpoint.load() is None


def test_load_rejects_symlinked_pointer(cache_root, tmp_path) -> None:
    checkpoint = _checkpoint(cache_root)
    checkpoint.save(b"payload")
    external = tmp_path / "external-pointer.json"
    external.write_text(
        json.dumps({"sha256": hashlib.sha256(b"payload").hexdigest()}), encoding="utf-8"
    )
    checkpoint.pointer.unlink()
    checkpoint.pointer.symlink_to(external)

    assert checkpoint.load() is None


def test_load_rejects_symlinked_archive(cache_root, tmp_path) -> None:
    checkpoint = _checkpoint(cache_root)
    payload = b"payload"
    checkpoint.save(payload)
    external = tmp_path / "external.zip"
    external.write_bytes(payload)
    archive = checkpoint.directory / _archive_name(payload)
    archive.unlink()
    archive.symlink_to(external)

    assert checkpoint.load() is None


# ---------------------------------------------------------------------------
# concurrent writers: atomic replace keeps pointer and archive consistent
# ---------------------------------------------------------------------------


def test_concurrent_saves_keep_pointer_consistent_with_loaded_archive(
    cache_root,
) -> None:
    checkpoint = _checkpoint(cache_root)
    payloads = [f"writer-{i}".encode() for i in range(8)]
    errors: list[Exception] = []

    def save(payload: bytes) -> None:
        try:
            checkpoint.save(payload)
        except Exception as exc:  # pragma: no cover - surfaced below
            errors.append(exc)

    threads = [threading.Thread(target=save, args=(payload,)) for payload in payloads]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert not errors
    # Every archive is fully written and the pointer references one of them.
    loaded = checkpoint.load()
    assert loaded in payloads
    digests = {hashlib.sha256(payload).hexdigest() for payload in payloads}
    assert json.loads(checkpoint.pointer.read_text(encoding="utf-8"))["sha256"] in digests
    names = {path.name for path in checkpoint.directory.iterdir()}
    assert names == {*(f"{digest}.zip" for digest in digests), "ready.json"}


def test_concurrent_reader_never_observes_partial_checkpoint(cache_root) -> None:
    checkpoint = _checkpoint(cache_root)
    payloads = [b"alpha-archive", b"beta-archive", b"gamma-archive"]
    done = threading.Event()
    observations: list[bytes | None] = []
    errors: list[Exception] = []

    def writer() -> None:
        try:
            for _ in range(40):
                for payload in payloads:
                    checkpoint.save(payload)
        except Exception as exc:  # pragma: no cover - surfaced below
            errors.append(exc)
        finally:
            done.set()

    def reader() -> None:
        while not done.is_set():
            observations.append(checkpoint.load())

    writer_thread = threading.Thread(target=writer)
    reader_thread = threading.Thread(target=reader, daemon=True)
    writer_thread.start()
    reader_thread.start()
    writer_thread.join()
    done.wait(timeout=10)
    reader_thread.join(timeout=10)

    assert not errors
    # ``None`` is the legitimate degraded read before the first save lands;
    # every successful read must be a complete, integrity-verified payload.
    assert all(observation is None or observation in payloads for observation in observations)
    assert any(observation in payloads for observation in observations)
    assert checkpoint.load() in payloads
