"""Data models for NER extraction results."""

from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field

from backend.graph.schema import EntityType, RelationshipType


class ExtractionSource(str, Enum):
    """Source of entity extraction."""

    SPACY = "spacy"
    GAZETTEER = "gazetteer"
    LLM = "llm"
    HYBRID = "hybrid"  # Multiple sources agreed


class ExtractedEntity(BaseModel):
    """An entity extracted from text."""

    text: str  # Original text as found
    normalized_name: str  # Normalized/canonical name
    entity_type: EntityType
    span: Optional[tuple[int, int]] = None  # (start, end) in source text
    confidence: float = Field(ge=0.0, le=1.0, default=0.5)
    source: ExtractionSource = ExtractionSource.SPACY
    graph_id: Optional[str] = None  # Linked graph entity ID
    gazetteer_id: Optional[str] = None  # ID from gazetteer if matched
    metadata: dict = Field(default_factory=dict)

    def __hash__(self):
        return hash((self.normalized_name, self.entity_type))

    def __eq__(self, other):
        if not isinstance(other, ExtractedEntity):
            return False
        return (
            self.normalized_name == other.normalized_name
            and self.entity_type == other.entity_type
        )


class ExtractedRelationship(BaseModel):
    """A relationship between extracted entities."""

    source_entity_name: str
    target_entity_name: str
    relationship_type: RelationshipType
    confidence: float = Field(ge=0.0, le=1.0, default=0.5)
    evidence: str = ""  # The text supporting this relationship


class ExtractionResult(BaseModel):
    """Complete result of NER extraction."""

    entities: list[ExtractedEntity] = Field(default_factory=list)
    relationships: list[ExtractedRelationship] = Field(default_factory=list)
    source_text: str = ""
    session_id: Optional[str] = None
    processing_time_ms: float = 0.0

    @property
    def entity_count(self) -> int:
        return len(self.entities)

    @property
    def relationship_count(self) -> int:
        return len(self.relationships)

    def get_entities_by_type(self, entity_type: EntityType) -> list[ExtractedEntity]:
        """Get all entities of a specific type."""
        return [e for e in self.entities if e.entity_type == entity_type]


class GazetteerEntry(BaseModel):
    """A single entry in a gazetteer."""

    id: str
    name: str
    entity_type: EntityType
    aliases: list[str] = Field(default_factory=list)
    patterns: list[str] = Field(default_factory=list)  # Regex patterns
    metadata: dict = Field(default_factory=dict)

    @property
    def all_names(self) -> list[str]:
        """Get all names including aliases."""
        return [self.name] + self.aliases
