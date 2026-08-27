"""Centralized Gemini prompt construction.

Keeping prompts out of handlers/services makes them easy to review and tune
independently of business logic. Every prompt in this module enforces the
same non-negotiable rules from the spec: never invent content, never
"correct" names/numbers/dates/amounts, mark anything uncertain instead of
guessing, and always return the DocumentResult JSON shape.
"""

from __future__ import annotations

from app.schemas.extraction import DocumentResult

_CORE_RULES = """
You are a meticulous document digitization engine. You convert scanned,
photographed, handwritten, or digitally-authored documents into structured
JSON. Follow these rules exactly, without exception:

1. Preserve the original text exactly as written. Do not paraphrase,
   summarize, translate, or "clean up" wording.
2. Never invent or guess characters, words, numbers, dates, names, document
   numbers, or monetary amounts that are not clearly legible. If a value is
   unclear, illegible, or ambiguous, set "uncertain": true and put your best
   literal reading (or an empty string if nothing is legible) in "value" -
   never fabricate a plausible-looking replacement.
3. Never "correct" apparent typos, spelling variants, or formatting in
   names, passport/document numbers, dates, legal references, or monetary
   amounts. Reproduce them exactly as they appear in the source, even if
   they look inconsistent or wrong.
4. Preserve numbers and dates exactly as formatted in the source (do not
   normalize date formats, do not add/remove leading zeros, do not convert
   number formats).
5. Detect the natural language of the document content. It is very likely
   to be one of: Uzbek (Latin script), Uzbek (Cyrillic script), Russian, or
   English - but detect whatever is actually present. Do not translate the
   document unless explicitly told to in this prompt.
6. Preserve structure: headings (with heading level if discernible),
   paragraphs, numbered lists, bullet lists, and tables (with headers and
   rows). Preserve reading order as closely as possible.
7. Identify, where present: full names, dates, document/passport/reference
   numbers, monetary amounts, addresses, signatures (describe location,
   e.g. "signature block bottom left", do not invent a name for an
   illegible signature), and stamps/seals (describe visible text if legible).
8. Assign a confidence score between 0.0 and 1.0 to every extracted value,
   heading, paragraph, and table based on how legible/certain the source
   content was.
9. Record the 1-based source page number for every block when page
   boundaries are known.
10. Distinguish clearly between content that is literally extracted from the
    document and anything you are inferring (e.g. a document_type
    classification). Only literal extractions belong in text_blocks and
    entities.
11. If you cannot process the document at all, or a page is blank/corrupt,
    add a human-readable note to the "warnings" array instead of omitting
    it silently.
12. Return ONLY valid JSON matching the required schema. Do not include
    markdown code fences, commentary, or explanation outside the JSON.

IMPORTANT ABOUT THE OUTPUT SHAPE:
Put every piece of document content, in reading order, into the single
"text_blocks" array. Each entry has a "type" of one of: heading, paragraph,
list, table, signature, stamp, other - and only the fields relevant to that
type should be filled in:
  - type="heading":   set "text" and "level" (1-6)
  - type="paragraph", "signature", "stamp", "other": set "text"
  - type="list":       set "ordered" (true/false) and "items" (each with
                        "text" and "level")
  - type="table":       set "table" with "headers" (list of column names)
                        and "rows" (list of rows, each a list of cell
                        strings), plus an optional "title"
Leave the top-level "headings", "paragraphs", "tables", "lists" arrays
EMPTY - they are computed automatically from text_blocks. Do not duplicate
content into them.
"""

# Uzbek is a primary target language for this system and its handwriting is
# where recognition quality matters most (see spec section 5). This block is
# always included in the vision prompt (not only when handwriting is
# suspected) because these are systematic script-level ambiguities that
# affect printed text too, and because a single page can silently mix
# Cyrillic and Latin Uzbek.
_UZBEK_SCRIPT_GUIDANCE = """
UZBEK-SPECIFIC GUIDANCE (apply whenever the content looks like Uzbek, in
either script - this is one of the most common and most error-prone cases
for this system):

- A single document, or even a single page, may mix Uzbek Cyrillic, Uzbek
  Latin, and Russian. Do not assume one script for the whole document -
  identify the script actually used in each block/line, and set the
  "language" field to whichever single language is dominant overall.

- Uzbek Latin has two letters built from a base letter plus a modifier
  character that looks like an apostrophe: "o'" / "oʻ" / "o‘" (o + modifier)
  and "g'" / "gʻ" / "g‘" (g + modifier). In handwriting and in print, this
  modifier is written inconsistently - as a straight apostrophe ('), a
  curly comma-like mark (ʻ or ‘), a backtick, or sometimes omitted
  entirely. Do NOT normalize it to a "canonical" character and do NOT treat
  it as ordinary punctuation to be cleaned up - reproduce exactly the mark
  the writer used, per rule 3 above (never silently "correct" spelling or
  formatting). Also do not confuse a genuine apostrophe-modifier letter
  with a nearby quotation mark used for actual quoted text.

- Uzbek Latin "sh" and "ch" are two-letter digraphs representing single
  sounds. Keep them as written (do not split or merge them with
  neighboring letters).

- Uzbek Cyrillic has four letters that are easy to misread as a similar,
  much more common Russian/Cyrillic letter, especially in handwriting where
  the distinguishing mark is small and easily smudged or lost:
    * Ў (u with breve)   vs  У  (plain u)
    * Қ (q with descender) vs  К  (plain k)
    * Ғ (g with breve/descender) vs  Г  (plain g)
    * Ҳ (h with descender) vs  Х  (plain kh)
  Look carefully for the diacritic/descender before deciding between each
  pair. If you genuinely cannot tell which of a pair was written, mark that
  character/word as uncertain rather than guessing the more common variant.

- Also watch for common Cyrillic cursive-handwriting confusions unrelated
  to Uzbek specifically: И vs Й (the breve over Й is often faint), Ш vs Щ
  (the small tail on Щ), Ц vs Ц-like letters, and Е vs Ё (the two dots on Ё
  are frequently dropped in handwriting - if you cannot see the dots but
  the word is clearly "yo"-sounding in context, still prefer the literal
  glyph shape you can see and mark it uncertain rather than inferring Ё).

- Dates in Uzbek documents are most commonly written DD.MM.YYYY or as
  "<day> <month name> <year>" with the month name in Uzbek or Russian.
  Preserve whichever format and whichever language the month name is
  actually written in - do not convert between formats or languages.
"""


def build_text_structuring_prompt(page_texts: dict[int, str], filename_hint: str) -> str:
    """Prompt used for digitally-authored PDFs where text was already
    extracted locally with PyMuPDF (no vision call needed - cost control).
    """
    pages_section = "\n\n".join(
        f"--- PAGE {page_num} ---\n{text}" for page_num, text in sorted(page_texts.items())
    )
    return f"""{_CORE_RULES}

The text below was extracted directly from a digital PDF's text layer using
a PDF library (not OCR), so character recognition is already reliable - your
job is to structure it, not re-read it. Preserve the extracted characters
verbatim; only decide how to organize them into headings/paragraphs/
lists/tables/entities.

Source filename (context only, do not treat as document content): {filename_hint}

{pages_section}

Return a single JSON object matching the DocumentResult schema.
"""


def build_vision_extraction_prompt(page_numbers: list[int], is_handwritten_hint: bool) -> str:
    """Prompt used when sending rendered page images to Gemini Vision."""
    handwriting_note = (
        "\nThis document may contain handwriting. Handwriting recognition is "
        "inherently uncertain - be conservative, mark low-confidence "
        "characters/words as uncertain, and never guess a 'reasonable' "
        "replacement for illegible handwriting.\n"
        if is_handwritten_hint
        else ""
    )
    pages_note = ", ".join(str(p) for p in page_numbers)
    return f"""{_CORE_RULES}
{_UZBEK_SCRIPT_GUIDANCE}
{handwriting_note}
You are given page images in order, corresponding to source page numbers:
{pages_note}

Read every page image carefully and extract its full content following the
rules above. Set source_page to the actual page number for each block/value.

Return a single JSON object matching the DocumentResult schema.
"""


def schema_hint() -> dict:
    """JSON schema (OpenAPI-style) used as response_schema for Gemini's
    structured output mode."""
    return DocumentResult.model_json_schema()
