"""Contract tests for partners.helpers public functions.

``safe_filename``, ``split_message`` basics and the markdown-table trio have
dedicated regression suites elsewhere; this file covers the remaining public
helpers (``detect_image_mime``, ``ensure_dir``, ``timestamp``) and the
``split_message`` break-point selection branches (newline → space → hard cut).
"""

from __future__ import annotations

from datetime import datetime, timedelta

from deeptutor.partners.helpers import (
    detect_image_mime,
    ensure_dir,
    split_message,
    timestamp,
)


class TestDetectImageMime:
    def test_png_magic_bytes(self):
        assert detect_image_mime(b"\x89PNG\r\n\x1a\n" + b"rest") == "image/png"

    def test_jpeg_magic_bytes(self):
        assert detect_image_mime(b"\xff\xd8\xff\xe0" + b"rest") == "image/jpeg"

    def test_gif87a(self):
        assert detect_image_mime(b"GIF87a" + b"rest") == "image/gif"

    def test_gif89a(self):
        assert detect_image_mime(b"GIF89a" + b"rest") == "image/gif"

    def test_webp_riff_container(self):
        assert detect_image_mime(b"RIFF\x00\x00\x00\x00WEBPrest") == "image/webp"

    def test_riff_without_webp_is_not_image(self):
        assert detect_image_mime(b"RIFF\x00\x00\x00\x00WAVE") is None

    def test_unknown_bytes(self):
        assert detect_image_mime(b"<html>not an image</html>") is None

    def test_empty_bytes(self):
        assert detect_image_mime(b"") is None


class TestEnsureDir:
    def test_creates_nested_directories(self, tmp_path):
        target = tmp_path / "a" / "b" / "c"
        result = ensure_dir(target)
        assert result == target
        assert target.is_dir()

    def test_existing_directory_is_idempotent(self, tmp_path):
        ensure_dir(tmp_path)
        assert ensure_dir(tmp_path) == tmp_path


class TestTimestamp:
    def test_returns_parseable_iso_string(self):
        value = timestamp()
        parsed = datetime.fromisoformat(value)
        assert parsed.tzinfo is None  # naive local time, like datetime.now()

    def test_value_is_current(self):
        parsed = datetime.fromisoformat(timestamp())
        now = datetime.now()
        assert abs(now - parsed) < timedelta(seconds=5)


class TestSplitMessageBreakPoints:
    def test_empty_content(self):
        assert split_message("") == []

    def test_short_content_single_chunk(self):
        assert split_message("hello") == ["hello"]

    def test_prefers_newline_break(self):
        chunks = split_message("ab\ncd\nef", max_len=5)
        assert chunks == ["ab", "cd\nef"]
        assert all(len(c) <= 5 for c in chunks)

    def test_falls_back_to_space_break(self):
        chunks = split_message("aaa bbb ccc", max_len=7)
        assert chunks == ["aaa", "bbb ccc"]

    def test_hard_break_when_no_separator(self):
        chunks = split_message("aaaaaaaaaa", max_len=4)
        assert chunks == ["aaaa", "aaaa", "aa"]

    def test_newline_at_cut_start_treated_as_hard_break(self):
        # A newline at index 0 of the cut window cannot advance the pointer,
        # so the splitter must fall back to a hard cut instead of looping.
        assert split_message("\nabcdef", max_len=4) == ["\nabc", "def"]

    def test_chunks_are_lstripped_after_break(self):
        chunks = split_message("one\ntwo", max_len=4)
        assert chunks[1] == "two"
