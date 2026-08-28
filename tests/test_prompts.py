"""Tests that the prompt-construction functions include the guidance they
are supposed to - not a test of Gemini's actual output (no network call).
"""

from __future__ import annotations

from app.services.prompts import (
    build_text_structuring_prompt,
    build_vision_extraction_prompt,
    build_voice_transcription_prompt,
)


def test_vision_prompt_includes_uzbek_script_guidance():
    prompt = build_vision_extraction_prompt(page_numbers=[1], is_handwritten_hint=True)

    # Cyrillic look-alike pairs that are easy to misread in handwriting.
    for letter_pair in ("Ў", "Қ", "Ғ", "Ҳ"):
        assert letter_pair in prompt

    # The Latin apostrophe-letter guidance (oʻ/gʻ) must instruct preserving
    # the writer's actual glyph rather than normalizing it.
    assert "o'" in prompt or "oʻ" in prompt
    assert "do NOT normalize" in prompt or "Do NOT normalize" in prompt


def test_vision_prompt_includes_handwriting_caution_when_hinted():
    prompt = build_vision_extraction_prompt(page_numbers=[1], is_handwritten_hint=True)
    assert "handwriting" in prompt.lower()

    prompt_without_hint = build_vision_extraction_prompt(page_numbers=[1], is_handwritten_hint=False)
    assert "inherently uncertain" not in prompt_without_hint


def test_vision_prompt_includes_page_numbers():
    prompt = build_vision_extraction_prompt(page_numbers=[3, 4, 5], is_handwritten_hint=False)
    assert "3, 4, 5" in prompt


def test_text_structuring_prompt_does_not_duplicate_vision_only_guidance():
    # The Uzbek script/handwriting guidance is about *visual* recognition
    # ambiguity - irrelevant once PyMuPDF has already decoded the text layer
    # to real Unicode characters, so it must not bloat this prompt.
    prompt = build_text_structuring_prompt({1: "Some already-decoded text."}, "file.pdf")
    assert "breve" not in prompt
    assert "descender" not in prompt


def test_core_rules_forbid_inventing_content_in_both_prompts():
    text_prompt = build_text_structuring_prompt({1: "text"}, "file.pdf")
    vision_prompt = build_vision_extraction_prompt(page_numbers=[1], is_handwritten_hint=False)
    for prompt in (text_prompt, vision_prompt):
        assert "Never invent or guess" in prompt


def test_voice_prompt_requires_grammatical_normalization():
    prompt = build_voice_transcription_prompt()
    assert "grammatical and orthographic" in prompt


def test_voice_prompt_allows_contextual_reconstruction_of_unclear_audio():
    prompt = build_voice_transcription_prompt()
    assert "reconstruct the most logical wording" in prompt


def test_voice_prompt_forbids_fabricating_unspoken_content():
    prompt = build_voice_transcription_prompt()
    assert "Never add information" in prompt
    assert "never invent content that was not" in prompt


def test_voice_prompt_requires_transcribing_the_full_audio():
    # Regression: a real multi-participant call recording was only
    # transcribed up through the first speaker's greeting - the model
    # treated that as the end of the audio and stopped, silently dropping
    # every other participant's speech.
    prompt = build_voice_transcription_prompt()
    assert "ENTIRE audio" in prompt
    assert "never stop early" in prompt


def test_voice_prompt_requires_transcribing_every_speaker():
    prompt = build_voice_transcription_prompt()
    assert "more than one speaker" in prompt
    assert "do not stop after the first speaker" in prompt


def test_voice_prompt_handles_silence_as_empty_string():
    prompt = build_voice_transcription_prompt()
    assert "output an empty string" in prompt


def test_voice_prompt_does_not_reuse_document_json_schema_language():
    # This is a plain-text transcription prompt, not the structured
    # DocumentResult JSON extraction prompt - it must not carry over the
    # document-specific output-shape instructions.
    prompt = build_voice_transcription_prompt()
    assert "text_blocks" not in prompt
    assert "response_schema" not in prompt
    assert "headings" not in prompt
