"""Data models for audio transcription and speaker diarization."""

from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field


class AudioJobPhase(str, Enum):
    """Processing phase of an audio transcription job."""

    UPLOADING = "uploading"
    TRANSCRIBING = "transcribing"
    AWAITING_MAPPING = "awaiting_mapping"
    PROCESSING_TRANSCRIPT = "processing_transcript"
    COMPLETED = "completed"
    FAILED = "failed"


class DiarizedSegment(BaseModel):
    """A single segment from diarized transcription."""

    speaker: int  # Speaker index from Deepgram (0, 1, 2, ...)
    text: str
    start: float  # Start time in seconds
    end: float  # End time in seconds
    confidence: float = 0.0


class SpeakerSample(BaseModel):
    """Sample utterances for a detected speaker, used for identification."""

    speaker_index: int
    utterance_count: int
    total_duration: float  # Total speaking time in seconds
    sample_texts: list[str] = Field(default_factory=list)  # First N utterances


class DiarizedTranscript(BaseModel):
    """Complete diarized transcription result."""

    segments: list[DiarizedSegment] = Field(default_factory=list)
    speaker_count: int = 0
    speaker_samples: list[SpeakerSample] = Field(default_factory=list)
    total_duration: float = 0.0
    metadata: dict = Field(default_factory=dict)


class SpeakerMappingEntry(BaseModel):
    """Maps a detected speaker index to a player/character."""

    speaker_index: int
    role: str = "player"  # "dm" or "player"
    player_name: str
    character_name: Optional[str] = None


class SpeakerMappingRequest(BaseModel):
    """Request to map speakers and process the transcript."""

    mappings: list[SpeakerMappingEntry]
    session_number: Optional[int] = None
    campaign_id: Optional[str] = None


class AudioJob(BaseModel):
    """An audio transcription job tracking its progress through phases."""

    job_id: str
    filename: str
    phase: AudioJobPhase = AudioJobPhase.UPLOADING
    error: Optional[str] = None

    # Set after transcription completes
    diarized_transcript: Optional[DiarizedTranscript] = None

    # Set after processing completes
    transcript_result: Optional[dict] = None
