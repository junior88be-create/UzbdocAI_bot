"""Tests for storage helpers: random filenames, path-traversal protection,
and JSON round-tripping used for structured-result caching.
"""

from __future__ import annotations

import pytest

from app.utils import files


def test_generate_stored_filename_is_random_and_keeps_extension():
    name_a = files.generate_stored_filename(".pdf")
    name_b = files.generate_stored_filename(".pdf")
    assert name_a != name_b
    assert name_a.endswith(".pdf")


def test_save_bytes_writes_inside_storage_root():
    relative_path, absolute_path = files.save_bytes(b"hello", subdir="uploads", extension=".pdf")
    try:
        assert absolute_path.exists()
        assert absolute_path.read_bytes() == b"hello"
        assert relative_path.startswith("uploads/")
    finally:
        files.delete_if_exists(relative_path)
        assert not absolute_path.exists()


def test_absolute_path_for_rejects_path_traversal():
    with pytest.raises(files.UnsafePathError):
        files.absolute_path_for("../../etc/passwd")


def test_delete_if_exists_ignores_path_traversal_silently():
    # Must not raise and must not touch anything outside storage root.
    files.delete_if_exists("../../etc/passwd")


def test_save_and_load_json_for_document_round_trips():
    key = "test-key-12345"
    payload = '{"document_type": "letter", "language": "en", "pages": 1}'
    relative_path = files.save_json_for_document(key, payload)
    try:
        loaded = files.load_json_for_document(relative_path)
        assert loaded == payload
    finally:
        files.delete_if_exists(relative_path)


def test_build_zip_contains_all_entries_with_correct_content():
    entries = [("a.docx", b"docx-bytes"), ("b.xlsx", b"xlsx-bytes")]
    archive_bytes = files.build_zip(entries)

    import io
    import zipfile

    with zipfile.ZipFile(io.BytesIO(archive_bytes)) as archive:
        names = set(archive.namelist())
        assert names == {"a.docx", "b.xlsx"}
        assert archive.read("a.docx") == b"docx-bytes"
        assert archive.read("b.xlsx") == b"xlsx-bytes"


def test_build_zip_disambiguates_duplicate_filenames():
    entries = [("report.docx", b"first"), ("report.docx", b"second"), ("report.docx", b"third")]
    archive_bytes = files.build_zip(entries)

    import io
    import zipfile

    with zipfile.ZipFile(io.BytesIO(archive_bytes)) as archive:
        names = archive.namelist()
        assert len(names) == 3
        assert len(set(n.lower() for n in names)) == 3
        assert "report.docx" in names
        assert "report (1).docx" in names
        assert "report (2).docx" in names


def test_human_readable_size_formats_reasonably():
    assert files.human_readable_size(500) == "500 B"
    assert "KB" in files.human_readable_size(2048)
    assert "MB" in files.human_readable_size(5 * 1024 * 1024)
