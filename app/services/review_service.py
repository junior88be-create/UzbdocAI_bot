"""OCR review step: pure logic for enumerating uncertain content in a
DocumentResult and applying user-supplied corrections to it.

Kept free of aiogram/DB imports so it can be unit tested directly. The bot
handler (app/bot/handlers/review.py) owns the Telegram UI and persistence
around this.
"""

from __future__ import annotations

from dataclasses import dataclass

from app.schemas.extraction import DocumentResult


@dataclass
class ReviewItem:
    """One uncertain value/block, with a stable `ref` that
    apply_correction() can resolve back to the exact field in the result.
    """

    ref: str
    category: str
    page: int | None
    value: str
    confidence: float


_ENTITY_LABELS: dict[str, str] = {
    "names": "Исм",
    "dates": "Сана",
    "document_numbers": "Ҳужжат рақами",
    "amounts": "Сумма",
    "addresses": "Манзил",
    "signatures": "Имзо",
    "stamps": "Муҳр",
}

_TEXT_BLOCK_LABELS: dict[str, str] = {
    "heading": "Сарлавҳа",
    "paragraph": "Матн",
    "signature": "Имзо",
    "stamp": "Муҳр",
    "other": "Матн",
}


def collect_uncertain_items(result: DocumentResult) -> list[ReviewItem]:
    """Returns every uncertain value/block in reading + entity order."""
    items: list[ReviewItem] = []

    for index, block in enumerate(result.text_blocks):
        if block.type in _TEXT_BLOCK_LABELS and block.uncertain and block.text:
            items.append(
                ReviewItem(
                    ref=f"text_blocks:{index}",
                    category=_TEXT_BLOCK_LABELS[block.type],
                    page=block.source_page,
                    value=block.text,
                    confidence=block.confidence,
                )
            )
        elif block.type == "list" and block.items:
            for item_index, list_item in enumerate(block.items):
                if list_item.uncertain:
                    items.append(
                        ReviewItem(
                            ref=f"text_blocks:{index}.items:{item_index}",
                            category="Рўйхат банди",
                            page=block.source_page,
                            value=list_item.text,
                            confidence=block.confidence,
                        )
                    )
        elif block.type == "table" and block.table is not None and block.table.uncertain:
            items.append(
                ReviewItem(
                    ref=f"text_blocks:{index}.table",
                    category="Жадвал",
                    page=block.source_page,
                    value=block.table.title or "(номсиз жадвал)",
                    confidence=block.table.confidence,
                )
            )

    for field_name, label in _ENTITY_LABELS.items():
        for index, value in enumerate(getattr(result.entities, field_name)):
            if value.uncertain:
                items.append(
                    ReviewItem(
                        ref=f"entities.{field_name}:{index}",
                        category=label,
                        page=value.source_page,
                        value=value.value,
                        confidence=value.confidence,
                    )
                )

    return items


def apply_correction(result: DocumentResult, ref: str, new_value: str) -> bool:
    """Mutates `result` in place, resolving `ref` from collect_uncertain_items().

    Returns True if the ref was found and applied, False if it no longer
    exists (e.g. stale button after the item list changed).

    Callers should re-derive the flat arrays afterwards (e.g. via
    `DocumentResult.model_validate_json(result.model_dump_json())`) since
    in-place mutation does not automatically refresh them - see
    app/schemas/extraction.py for why those arrays are derived rather than
    kept in sync live.
    """
    new_value = new_value.strip()

    if ref.startswith("entities."):
        field_name, _, index_str = ref[len("entities.") :].partition(":")
        if not index_str.isdigit():
            return False
        index = int(index_str)
        values = getattr(result.entities, field_name, None)
        if values is None or index >= len(values):
            return False
        values[index].value = new_value
        values[index].uncertain = False
        values[index].confidence = 1.0
        return True

    if ref.startswith("text_blocks:"):
        remainder = ref[len("text_blocks:") :]

        if ".items:" in remainder:
            block_index_str, item_index_str = remainder.split(".items:", 1)
            if not (block_index_str.isdigit() and item_index_str.isdigit()):
                return False
            block_index, item_index = int(block_index_str), int(item_index_str)
            if block_index >= len(result.text_blocks):
                return False
            block = result.text_blocks[block_index]
            if item_index >= len(block.items):
                return False
            block.items[item_index].text = new_value
            block.items[item_index].uncertain = False
            return True

        if remainder.endswith(".table"):
            block_index_str = remainder[: -len(".table")]
            if not block_index_str.isdigit():
                return False
            block_index = int(block_index_str)
            if block_index >= len(result.text_blocks):
                return False
            block = result.text_blocks[block_index]
            if block.table is None:
                return False
            block.table.uncertain = False
            return True

        if not remainder.isdigit():
            return False
        block_index = int(remainder)
        if block_index >= len(result.text_blocks):
            return False
        block = result.text_blocks[block_index]
        block.text = new_value
        block.uncertain = False
        block.confidence = 1.0
        return True

    return False


def refresh(result: DocumentResult) -> DocumentResult:
    """Re-derives the flat arrays after one or more apply_correction() calls."""
    return DocumentResult.model_validate_json(result.model_dump_json())
