"""Data models for transcript processing."""

from datetime import datetime
from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field

from backend.graph.schema import EntityType
from backend.ner.models import ExtractedEntity, ExtractedRelationship


class SpeakerRole(str, Enum):
    """Role of a speaker in the session."""

    DM = "dm"  # Dungeon Master
    PLAYER = "player"  # Player
    UNKNOWN = "unknown"  # Unknown role


class Speaker(BaseModel):
    """A speaker in the transcript."""

    name: str
    role: SpeakerRole = SpeakerRole.UNKNOWN
    character_name: Optional[str] = None  # Character they're playing
    aliases: list[str] = Field(default_factory=list)  # Other names they might use

    def matches(self, name: str) -> bool:
        """Check if a name matches this speaker."""
        name_lower = name.lower().strip()
        if self.name.lower() == name_lower:
            return True
        if self.character_name and self.character_name.lower() == name_lower:
            return True
        return any(alias.lower() == name_lower for alias in self.aliases)


class TranscriptSegment(BaseModel):
    """A single segment/turn in the transcript."""

    index: int  # Position in transcript
    speaker: Optional[str] = None  # Speaker name/identifier
    speaker_role: SpeakerRole = SpeakerRole.UNKNOWN
    text: str
    timestamp: Optional[str] = None  # Original timestamp if present
    character_name: Optional[str] = None  # Character being played

    # Extraction results (populated during processing)
    entities: list[ExtractedEntity] = Field(default_factory=list)
    relationships: list[ExtractedRelationship] = Field(default_factory=list)


class ParsedTranscript(BaseModel):
    """A fully parsed transcript."""

    segments: list[TranscriptSegment] = Field(default_factory=list)
    speakers: list[Speaker] = Field(default_factory=list)
    raw_text: str = ""
    source_format: str = "unknown"  # plain, json, discord, vtt, etc.
    metadata: dict = Field(default_factory=dict)

    @property
    def segment_count(self) -> int:
        return len(self.segments)

    @property
    def speaker_count(self) -> int:
        return len(self.speakers)

    @property
    def full_text(self) -> str:
        """Get all text concatenated."""
        return "\n".join(seg.text for seg in self.segments)

    def get_segments_by_speaker(self, speaker_name: str) -> list[TranscriptSegment]:
        """Get all segments from a specific speaker."""
        return [s for s in self.segments if s.speaker == speaker_name]

    def get_dm_segments(self) -> list[TranscriptSegment]:
        """Get all DM segments."""
        return [s for s in self.segments if s.speaker_role == SpeakerRole.DM]


class ProcessingResult(BaseModel):
    """Result of processing a transcript."""

    session_id: str  # Created session entity ID
    session_number: Optional[int] = None
    campaign_id: Optional[str] = None

    # Statistics
    segments_processed: int = 0
    entities_extracted: int = 0
    entities_created: int = 0
    relationships_extracted: int = 0
    relationships_created: int = 0

    # Aggregated extractions
    all_entities: list[ExtractedEntity] = Field(default_factory=list)
    all_relationships: list[ExtractedRelationship] = Field(default_factory=list)

    # Entity breakdown by type
    entity_counts: dict[str, int] = Field(default_factory=dict)

    # Processing metadata
    processing_time_ms: float = 0.0
    errors: list[str] = Field(default_factory=list)

    def add_entity(self, entity: ExtractedEntity) -> None:
        """Add an entity to the result."""
        self.all_entities.append(entity)
        type_name = entity.entity_type.value
        self.entity_counts[type_name] = self.entity_counts.get(type_name, 0) + 1

    def summary(self) -> str:
        """Generate a summary string."""
        lines = [
            f"Session: {self.session_id}",
            f"Segments processed: {self.segments_processed}",
            f"Entities extracted: {self.entities_extracted}",
            f"Relationships extracted: {self.relationships_extracted}",
            "",
            "Entity breakdown:",
        ]
        for etype, count in sorted(self.entity_counts.items()):
            lines.append(f"  {etype}: {count}")
        return "\n".join(lines)
