"""Safe filesystem helpers for uploaded/generated documents.

Two rules enforced everywhere in this module:
1. Never trust a caller-supplied filename - all names written to disk are
   randomly generated (uuid4) with a fixed, validated extension.
2. Every path is resolved and checked to stay inside STORAGE_ROOT to prevent
   path traversal.
"""

from __future__ import annotations

import io
import uuid
import zipfile
from pathlib import Path

from app.config.settings import get_settings


class UnsafePathError(Exception):
    pass


def generate_stored_filename(extension: str) -> str:
    if not extension.startswith("."):
        extension = f".{extension}"
    return f"{uuid.uuid4().hex}{extension}"


def _resolve_within_storage(relative_path: str) -> Path:
    settings = get_settings()
    resolved = (settings.storage_path / relative_path).resolve()
    if settings.storage_path not in resolved.parents and resolved != settings.storage_path:
        raise UnsafePathError(f"Path escapes storage root: {relative_path}")
    return resolved


def save_bytes(data: bytes, subdir: str, extension: str) -> tuple[str, Path]:
    """Writes bytes under storage/<subdir>/ with a random filename.

    Returns (relative_path, absolute_path). relative_path is what gets
    persisted in the database - never the absolute filesystem path.
    """
    filename = generate_stored_filename(extension)
    relative_path = f"{subdir}/{filename}"
    absolute_path = _resolve_within_storage(relative_path)
    absolute_path.parent.mkdir(parents=True, exist_ok=True)
    absolute_path.write_bytes(data)
    return relative_path, absolute_path


def absolute_path_for(relative_path: str) -> Path:
    return _resolve_within_storage(relative_path)


def delete_if_exists(relative_path: str) -> None:
    try:
        path = _resolve_within_storage(relative_path)
    except UnsafePathError:
        return
    if path.exists() and path.is_file():
        path.unlink(missing_ok=True)


def reserve_output_path(subdir: str, extension: str) -> tuple[str, Path]:
    """Allocates a random filename/path for a generator (docx/openpyxl) to
    write to directly, without pre-writing content."""
    filename = generate_stored_filename(extension)
    relative_path = f"{subdir}/{filename}"
    absolute_path = _resolve_within_storage(relative_path)
    absolute_path.parent.mkdir(parents=True, exist_ok=True)
    return relative_path, absolute_path


def save_json_for_document(key: str, json_text: str) -> str:
    """Deterministic path keyed by `key` (a document id or content hash), so
    the structured extraction can be reloaded later without another Gemini
    call. Callers pass the content hash to enable cross-upload reuse for the
    same user (see spec section 19), or a document id otherwise.
    """
    relative_path = f"processed/{key}.json"
    absolute_path = _resolve_within_storage(relative_path)
    absolute_path.parent.mkdir(parents=True, exist_ok=True)
    absolute_path.write_text(json_text, encoding="utf-8")
    return relative_path


def load_json_for_document(relative_path: str) -> str:
    absolute_path = _resolve_within_storage(relative_path)
    return absolute_path.read_text(encoding="utf-8")


def build_zip(entries: list[tuple[str, bytes]]) -> bytes:
    """Bundles (filename, data) pairs into an in-memory ZIP archive.

    Used to deliver batch-processing output as one file instead of flooding
    the chat with N x (number of formats) separate messages. Duplicate
    filenames (e.g. two source documents sharing a name) are disambiguated.
    """
    buffer = io.BytesIO()
    used_names: set[str] = set()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        for name, data in entries:
            archive.writestr(_unique_zip_entry_name(name, used_names), data)
    return buffer.getvalue()


def _unique_zip_entry_name(name: str, used: set[str]) -> str:
    if name.lower() not in used:
        used.add(name.lower())
        return name

    stem, dot, ext = name.rpartition(".")
    suffix = 1
    while True:
        candidate = f"{stem} ({suffix}){dot}{ext}" if dot else f"{name} ({suffix})"
        if candidate.lower() not in used:
            used.add(candidate.lower())
            return candidate
        suffix += 1


def human_readable_size(size_bytes: int) -> str:
    size = float(size_bytes)
    for unit in ("B", "KB", "MB", "GB"):
        if size < 1024:
            return f"{size:.1f} {unit}" if unit != "B" else f"{int(size)} {unit}"
        size /= 1024
    return f"{size:.1f} TB"
