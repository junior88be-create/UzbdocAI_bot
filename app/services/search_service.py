"""Pure logic for building a search-result preview snippet.

The actual full-text query runs in Postgres (DocumentRepository.search) -
this module only turns the matched document's stored search_text into a
short, safely HTML-escaped preview centered on the first matching query
word, for display in Telegram (parse_mode=HTML).
"""

from __future__ import annotations

import html

_CONTEXT_CHARS = 60


def build_snippet(search_text: str | None, query: str, context_chars: int = _CONTEXT_CHARS) -> str:
    """Returns an HTML-safe snippet of `search_text` around the first word
    of `query` found in it (case-insensitive), or "" if nothing matches
    (e.g. the match was only on the filename, not the content)."""
    if not search_text:
        return ""

    lowered = search_text.lower()
    for word in query.lower().split():
        word = word.strip('"' + "'-")
        if not word:
            continue
        index = lowered.find(word)
        if index == -1:
            continue

        start = max(0, index - context_chars)
        end = min(len(search_text), index + len(word) + context_chars)
        raw_snippet = search_text[start:end].strip()

        prefix = "…" if start > 0 else ""
        suffix = "…" if end < len(search_text) else ""
        return html.escape(f"{prefix}{raw_snippet}{suffix}")

    return ""
