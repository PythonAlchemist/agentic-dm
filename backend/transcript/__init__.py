"""Transcript processing module for D&D session transcripts.

This module provides:
- Parsing of various transcript formats (plain text, JSON, chat logs)
- Speaker diarization and turn segmentation
- NER extraction integration
- Session creation and graph population
"""

from backend.transcript.models import (
    ParsedTranscript,
    TranscriptSegment,
    Speaker,
    ProcessingResult,
)
from backend.transcript.parser import TranscriptParser
from backend.transcript.processor import TranscriptProcessor

__all__ = [
    "ParsedTranscript",
    "TranscriptSegment",
    "Speaker",
    "ProcessingResult",
    "TranscriptParser",
    "TranscriptProcessor",
]
