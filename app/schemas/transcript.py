"""Schema for structured voice/audio transcription output.

Deliberately separate from app/schemas/extraction.py::DocumentResult - voice
transcription is a different task (see
prompts.build_voice_transcription_prompt) with a much simpler, flat shape:
an ordered list of per-speaker segments, each with a start time.
"""

from __future__ import annotations

from pydantic import BaseModel, Field


class TranscriptSegment(BaseModel):
    speaker: str = Field(
        description=(
            "Speaker label: the speaker's own stated name if they identify "
            "themselves in the audio, otherwise a consistent generic label "
            "such as 'Спикер 1', 'Спикер 2' in first-speaking order."
        )
    )
    start_time: str = Field(
        description="Timestamp this segment starts at, formatted MM:SS (or HH:MM:SS past one hour)."
    )
    text: str = Field(description="The transcribed, grammatically-corrected text spoken in this segment.")


class VoiceTranscript(BaseModel):
    language: str = "unknown"
    segments: list[TranscriptSegment] = Field(default_factory=list)
