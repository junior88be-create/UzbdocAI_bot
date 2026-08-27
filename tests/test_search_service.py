"""Tests for the search-result snippet builder (pure logic - the actual
full-text query runs in Postgres and isn't exercised here, see README
"Known limitations" for why DB-touching tests aren't in this suite).
"""

from __future__ import annotations

from app.services.search_service import build_snippet


def test_build_snippet_returns_empty_for_missing_search_text():
    assert build_snippet(None, "invoice") == ""
    assert build_snippet("", "invoice") == ""


def test_build_snippet_finds_matching_word_case_insensitive():
    text = "This is a long paragraph mentioning an INVOICE number somewhere in the middle."
    snippet = build_snippet(text, "invoice")
    assert "INVOICE" in snippet


def test_build_snippet_adds_ellipsis_when_truncated():
    text = "x" * 200 + " invoice " + "y" * 200
    snippet = build_snippet(text, "invoice", context_chars=20)
    assert snippet.startswith("…")
    assert snippet.endswith("…")


def test_build_snippet_no_ellipsis_when_match_near_edges():
    text = "invoice at the very start of a short text"
    snippet = build_snippet(text, "invoice", context_chars=100)
    assert not snippet.startswith("…")


def test_build_snippet_returns_empty_when_no_query_word_matches():
    text = "Nothing relevant is written here at all."
    assert build_snippet(text, "invoice") == ""


def test_build_snippet_escapes_html_special_characters():
    text = "Value <b>invoice</b> & more <script>alert(1)</script>"
    snippet = build_snippet(text, "invoice")
    assert "<script>" not in snippet
    assert "&lt;" in snippet or "&amp;" in snippet


def test_build_snippet_strips_quotes_from_query_words():
    text = "the total invoice amount was correct"
    snippet = build_snippet(text, '"invoice"')
    assert "invoice" in snippet


def test_build_snippet_tries_each_query_word_until_one_matches():
    text = "Only the second search term appears here: amount."
    snippet = build_snippet(text, "invoice amount")
    assert "amount" in snippet
