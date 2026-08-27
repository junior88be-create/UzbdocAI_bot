"""File-upload validation and access-control helpers.

Uploaded files are treated as hostile input: extension, declared MIME type,
and actual file magic bytes are all cross-checked, and nothing is ever
executed or interpreted - only parsed by well-scoped libraries (PyMuPDF,
Pillow).
"""

from __future__ import annotations

from dataclasses import dataclass

ALLOWED_EXTENSIONS: set[str] = {".pdf", ".jpg", ".jpeg", ".png"}

ALLOWED_MIME_TYPES: set[str] = {
    "application/pdf",
    "image/jpeg",
    "image/png",
}

# Magic-byte signatures for the file types we actually accept - a cheap but
# effective guard against a renamed .exe/.zip masquerading as a PDF/image.
_MAGIC_SIGNATURES: dict[str, tuple[bytes, ...]] = {
    "application/pdf": (b"%PDF-",),
    "image/jpeg": (b"\xff\xd8\xff",),
    "image/png": (b"\x89PNG\r\n\x1a\n",),
}


@dataclass(frozen=True)
class FileValidationError(Exception):
    reason: str

    def __str__(self) -> str:
        return self.reason


def validate_extension(filename: str) -> str:
    lowered = filename.lower().strip()
    for ext in ALLOWED_EXTENSIONS:
        if lowered.endswith(ext):
            return ext
    raise FileValidationError(
        "Қўллаб-қувватланмайдиган файл кенгайтмаси. Рухсат этилган: PDF, JPG, JPEG, PNG."
    )


def validate_mime_type(mime_type: str | None) -> str:
    if not mime_type or mime_type not in ALLOWED_MIME_TYPES:
        raise FileValidationError(
            "Қўллаб-қувватланмайдиган файл тури. Рухсат этилган: PDF, JPG, PNG."
        )
    return mime_type


def validate_magic_bytes(head: bytes, mime_type: str) -> None:
    signatures = _MAGIC_SIGNATURES.get(mime_type, ())
    if not signatures or not any(head.startswith(sig) for sig in signatures):
        raise FileValidationError(
            "Файл мазмуни унинг эълон қилинган турига мос келмайди. "
            "Файл шикастланган ёки номи ўзгартирилган бўлиши мумкин."
        )


def validate_file_size(size_bytes: int, max_size_bytes: int) -> None:
    if size_bytes <= 0:
        raise FileValidationError("Файл бўш.")
    if size_bytes > max_size_bytes:
        max_mb = max_size_bytes // (1024 * 1024)
        raise FileValidationError(f"Файл жуда катта. Максимал рухсат этилган ҳажм: {max_mb} MB.")
