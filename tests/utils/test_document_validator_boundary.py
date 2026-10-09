from __future__ import annotations

import os

import pytest

from deeptutor.utils.document_validator import DocumentValidator


def test_validate_upload_safety_accepts_file_at_max_size_boundary() -> None:
    safe_name = DocumentValidator.validate_upload_safety("doc.pdf", DocumentValidator.MAX_FILE_SIZE)

    assert safe_name == "doc.pdf"


def test_validate_upload_safety_rejects_file_one_byte_over_max_size() -> None:
    with pytest.raises(ValueError) as excinfo:
        DocumentValidator.validate_upload_safety("doc.pdf", DocumentValidator.MAX_FILE_SIZE + 1)

    message = str(excinfo.value)
    assert "File too large" in message
    assert str(DocumentValidator.MAX_FILE_SIZE + 1) in message
    assert str(DocumentValidator.MAX_FILE_SIZE) in message


def test_validate_upload_safety_size_check_precedes_extension_check() -> None:
    with pytest.raises(ValueError, match="File too large"):
        DocumentValidator.validate_upload_safety("evil.exe", DocumentValidator.MAX_FILE_SIZE + 1)


def test_validate_upload_safety_none_size_skips_size_validation() -> None:
    assert DocumentValidator.validate_upload_safety("doc.pdf", None) == "doc.pdf"


def test_validate_upload_safety_strips_control_and_null_bytes() -> None:
    safe_name = DocumentValidator.validate_upload_safety("re\x00port\x1b\n\x7f.TXT", 10)

    assert safe_name == "report.txt"


def test_validate_upload_safety_replaces_dangerous_characters_with_underscore() -> None:
    safe_name = DocumentValidator.validate_upload_safety('a<b>c:d"e|f?g*h.PDF', 10)

    assert safe_name == "a_b_c_d_e_f_g_h.pdf"


def test_validate_upload_safety_normalizes_unicode_to_nfc() -> None:
    safe_name = DocumentValidator.validate_upload_safety("cafe\u0301.pdf", 10)

    assert safe_name == "caf\u00e9.pdf"


@pytest.mark.parametrize("bad_name", ["", "///"])
def test_validate_upload_safety_rejects_empty_after_sanitization(bad_name: str) -> None:
    with pytest.raises(ValueError, match="Invalid filename"):
        DocumentValidator.validate_upload_safety(bad_name, 10)


@pytest.mark.parametrize("bad_name", [".", ".."])
def test_validate_upload_safety_rejects_dot_directory_names(bad_name: str) -> None:
    with pytest.raises(ValueError, match="Invalid filename"):
        DocumentValidator.validate_upload_safety(bad_name, 10)


def test_validate_upload_safety_rejects_underscore_only_name() -> None:
    with pytest.raises(ValueError, match="Invalid filename"):
        DocumentValidator.validate_upload_safety("___", 10)


def test_validate_upload_safety_rejects_dotfile_under_allow_any_extension() -> None:
    with pytest.raises(ValueError, match="Invalid filename"):
        DocumentValidator.validate_upload_safety(".env", 10, allowed_extensions=set())


def test_validate_upload_safety_rejects_unsupported_extension() -> None:
    with pytest.raises(ValueError) as excinfo:
        DocumentValidator.validate_upload_safety("report.exe", 10)

    message = str(excinfo.value)
    assert "Unsupported file type" in message
    assert ".exe" in message


def test_validate_upload_safety_rejects_missing_extension() -> None:
    with pytest.raises(ValueError, match="Unsupported file type"):
        DocumentValidator.validate_upload_safety("README", 10)


def test_validate_upload_safety_matching_extension_prefers_longest_suffix() -> None:
    safe_name = DocumentValidator.validate_upload_safety(
        "a.tar.gz", 10, allowed_extensions={".gz", ".tar.gz"}
    )

    assert safe_name == "a.tar.gz"


def test_validate_upload_safety_policy_matching_is_case_insensitive() -> None:
    safe_name = DocumentValidator.validate_upload_safety("a.pdf", 10, allowed_extensions={".PDF"})

    assert safe_name == "a.pdf"


def test_validate_upload_safety_allow_any_extension_accepts_unknown_suffix() -> None:
    safe_name = DocumentValidator.validate_upload_safety(
        "data.parquet", 10, allowed_extensions=set()
    )

    assert safe_name == "data.parquet"


def test_validate_upload_safety_allow_any_extension_still_enforces_size() -> None:
    with pytest.raises(ValueError, match="File too large"):
        DocumentValidator.validate_upload_safety(
            "data.parquet", DocumentValidator.MAX_FILE_SIZE + 1, allowed_extensions=set()
        )


def test_validate_upload_safety_default_policy_rejects_disallowed_mime(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "deeptutor.utils.document_validator.mimetypes.guess_type",
        lambda _path: ("application/x-msdownload", None),
    )

    with pytest.raises(ValueError, match="MIME type validation failed"):
        DocumentValidator.validate_upload_safety("doc.pdf", 10)


def test_validate_upload_safety_default_policy_tolerates_unknown_mime(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "deeptutor.utils.document_validator.mimetypes.guess_type",
        lambda _path: (None, None),
    )

    assert DocumentValidator.validate_upload_safety("doc.pdf", 10) == "doc.pdf"


def test_validate_upload_safety_custom_policy_skips_mime_validation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "deeptutor.utils.document_validator.mimetypes.guess_type",
        lambda _path: ("application/x-blocked", None),
    )

    assert (
        DocumentValidator.validate_upload_safety("doc.pdf", 10, allowed_extensions={".pdf"})
        == "doc.pdf"
    )


def test_get_file_info_reports_allowed_extension_and_size_mb() -> None:
    info = DocumentValidator.get_file_info("report.PDF", 2621440)

    assert info["extension"] == ".pdf"
    assert info["is_allowed"] is True
    assert info["size_bytes"] == 2621440
    assert info["size_mb"] == 2.5


def test_get_file_info_flags_unknown_extension_as_not_allowed() -> None:
    info = DocumentValidator.get_file_info("photo.png", 1536)

    assert info["extension"] == ".png"
    assert info["is_allowed"] is False
    assert info["size_mb"] == 0.0


def test_validate_file_rejects_missing_path(tmp_path: os.PathLike) -> None:
    with pytest.raises(ValueError, match="File not found"):
        DocumentValidator.validate_file(str(os.path.join(tmp_path, "ghost.pdf")))


def test_validate_file_rejects_directory_path(tmp_path: os.PathLike) -> None:
    with pytest.raises(ValueError, match="Not a file"):
        DocumentValidator.validate_file(str(tmp_path))


@pytest.mark.skipif(
    not hasattr(os, "geteuid") or os.geteuid() == 0,
    reason="root ignores file permission bits",
)
def test_validate_file_rejects_unreadable_file(tmp_path: os.PathLike) -> None:
    path = os.path.join(tmp_path, "secret.pdf")
    with open(path, "wb") as fh:
        fh.write(b"%PDF-1.4\n")
    os.chmod(path, 0o000)

    try:
        with pytest.raises(ValueError, match="File not readable"):
            DocumentValidator.validate_file(path)
    finally:
        os.chmod(path, 0o644)


def test_validate_file_accepts_truncated_empty_document_without_content_check(
    tmp_path: os.PathLike,
) -> None:
    path = os.path.join(tmp_path, "empty.pdf")
    with open(path, "wb"):
        pass

    info = DocumentValidator.validate_file(path)

    assert info["size_bytes"] == 0
    assert info["is_allowed"] is True


def test_validate_file_accepts_misleading_extension_without_content_check(
    tmp_path: os.PathLike,
) -> None:
    path = os.path.join(tmp_path, "report.pdf")
    payload = b"plain text that is not a pdf document at all"
    with open(path, "wb") as fh:
        fh.write(payload)

    info = DocumentValidator.validate_file(path)

    assert info["filename"] == "report.pdf"
    assert info["size_bytes"] == len(payload)
    assert info["is_allowed"] is True


def test_validate_file_rejects_oversized_file(tmp_path: os.PathLike) -> None:
    path = os.path.join(tmp_path, "big.pdf")
    with open(path, "wb") as fh:
        fh.truncate(DocumentValidator.MAX_FILE_SIZE + 1)

    with pytest.raises(ValueError, match="File too large"):
        DocumentValidator.validate_file(path)
