"""Audio transcription module with speaker diarization.

Provides Deepgram-based transcription with speaker separation,
speaker-to-player mapping, and integration with the existing
transcript processing pipeline.
"""

from backend.audio.models import (
    AudioJob,
    AudioJobPhase,
    DiarizedSegment,
    DiarizedTranscript,
    SpeakerMappingEntry,
    SpeakerMappingRequest,
    SpeakerSample,
)
from backend.audio.transcriber import DeepgramTranscriber
from backend.audio.converter import DiarizedTranscriptConverter

__all__ = [
    "AudioJob",
    "AudioJobPhase",
    "DiarizedSegment",
    "DiarizedTranscript",
    "DiarizedTranscriptConverter",
    "DeepgramTranscriber",
    "SpeakerMappingEntry",
    "SpeakerMappingRequest",
    "SpeakerSample",
]
