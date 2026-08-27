"""Tests for file-upload validation, hashing, and safe path handling."""

from __future__ import annotations

import pytest

from app.utils.hashing import sha256_bytes, sha256_file
from app.utils.security import (
    FileValidationError,
    validate_extension,
    validate_file_size,
    validate_magic_bytes,
    validate_mime_type,
)


def test_validate_extension_accepts_allowed_types():
    assert validate_extension("report.PDF") == ".pdf"
    assert validate_extension("scan.jpeg") == ".jpeg"
    assert validate_extension("photo.png") == ".png"


def test_validate_extension_rejects_disallowed_types():
    with pytest.raises(FileValidationError):
        validate_extension("malware.exe")
    with pytest.raises(FileValidationError):
        validate_extension("archive.zip")


def test_validate_mime_type_accepts_allowed():
    assert validate_mime_type("application/pdf") == "application/pdf"
    assert validate_mime_type("image/png") == "image/png"


def test_validate_mime_type_rejects_disallowed_or_missing():
    with pytest.raises(FileValidationError):
        validate_mime_type("application/x-msdownload")
    with pytest.raises(FileValidationError):
        validate_mime_type(None)


def test_validate_magic_bytes_accepts_matching_signature():
    validate_magic_bytes(b"%PDF-1.7\n%rest", "application/pdf")
    validate_magic_bytes(b"\x89PNG\r\n\x1a\n\x00\x00", "image/png")


def test_validate_magic_bytes_rejects_mismatched_content():
    with pytest.raises(FileValidationError):
        validate_magic_bytes(b"MZ\x90\x00this is an exe", "application/pdf")


def test_validate_file_size_rejects_oversized_upload():
    with pytest.raises(FileValidationError):
        validate_file_size(60 * 1024 * 1024, max_size_bytes=50 * 1024 * 1024)


def test_validate_file_size_rejects_empty_upload():
    with pytest.raises(FileValidationError):
        validate_file_size(0, max_size_bytes=50 * 1024 * 1024)


def test_validate_file_size_accepts_within_limit():
    validate_file_size(10 * 1024 * 1024, max_size_bytes=50 * 1024 * 1024)


def test_sha256_bytes_is_deterministic_and_sensitive_to_content():
    digest_a = sha256_bytes(b"hello world")
    digest_b = sha256_bytes(b"hello world")
    digest_c = sha256_bytes(b"hello world!")

    assert digest_a == digest_b
    assert digest_a != digest_c
    assert len(digest_a) == 64


def test_sha256_file_matches_sha256_bytes(tmp_path):
    content = b"some file content for hashing"
    file_path = tmp_path / "sample.bin"
    file_path.write_bytes(content)

    assert sha256_file(file_path) == sha256_bytes(content)
