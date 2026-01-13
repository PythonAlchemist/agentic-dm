"""Knowledge graph schema definitions for D&D campaigns."""

from enum import Enum
from typing import Optional
from datetime import datetime

from pydantic import BaseModel, Field


class EntityType(str, Enum):
    """Types of entities in the campaign knowledge graph."""

    PC = "PC"  # Player Characters
    NPC = "NPC"  # Non-Player Characters
    LOCATION = "LOCATION"  # Places
    ITEM = "ITEM"  # Objects, weapons, artifacts
    MONSTER = "MONSTER"  # Creatures and enemies
    FACTION = "FACTION"  # Organizations
    QUEST = "QUEST"  # Quests and objectives
    EVENT = "EVENT"  # Significant happenings
    SESSION = "SESSION"  # Game session metadata
    SPELL = "SPELL"  # Spell definitions
    CLASS = "CLASS"  # Character classes
    RACE = "RACE"  # Character races
    RULE = "RULE"  # Game rules


class RelationshipType(str, Enum):
    """Types of relationships between entities."""

    # Spatial
    LOCATED_IN = "LOCATED_IN"
    CONTAINS = "CONTAINS"
    CONNECTED_TO = "CONNECTED_TO"

    # Social
    KNOWS = "KNOWS"
    ALLIED_WITH = "ALLIED_WITH"
    HOSTILE_TO = "HOSTILE_TO"
    MEMBER_OF = "MEMBER_OF"

    # Ownership
    OWNS = "OWNS"
    GUARDS = "GUARDS"

    # Quest/Narrative
    GAVE_QUEST = "GAVE_QUEST"
    PURSUING = "PURSUING"
    COMPLETED = "COMPLETED"
    OBJECTIVE_AT = "OBJECTIVE_AT"

    # Combat/Events
    KILLED = "KILLED"
    PARTICIPATED_IN = "PARTICIPATED_IN"
    OCCURRED_AT = "OCCURRED_AT"
    OCCURRED_IN = "OCCURRED_IN"

    # Reference
    INSTANCE_OF = "INSTANCE_OF"


class Entity(BaseModel):
    """Base entity model for the knowledge graph."""

    id: str
    name: str
    entity_type: EntityType
    description: Optional[str] = None
    aliases: list[str] = Field(default_factory=list)
    properties: dict = Field(default_factory=dict)
    source: Optional[str] = None  # Where this info came from
    confidence: float = 1.0  # NER confidence score
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)


class PCEntity(Entity):
    """Player Character entity."""

    entity_type: EntityType = EntityType.PC
    player_name: Optional[str] = None
    character_class: Optional[str] = None
    level: int = 1
    status: str = "alive"  # alive, dead, unknown


class NPCEntity(Entity):
    """Non-Player Character entity."""

    entity_type: EntityType = EntityType.NPC
    disposition: str = "neutral"  # friendly, neutral, hostile
    importance: str = "minor"  # major, minor, background


class LocationEntity(Entity):
    """Location entity."""

    entity_type: EntityType = EntityType.LOCATION
    location_type: Optional[str] = None  # city, dungeon, building, region
    visited: bool = False


class ItemEntity(Entity):
    """Item entity."""

    entity_type: EntityType = EntityType.ITEM
    rarity: Optional[str] = None  # common, uncommon, rare, etc.
    magical: bool = False
    owner_id: Optional[str] = None


class SessionEntity(Entity):
    """Session entity for tracking game sessions."""

    entity_type: EntityType = EntityType.SESSION
    session_number: int
    date: Optional[datetime] = None
    summary: Optional[str] = None
    transcript_id: Optional[str] = None


class Relationship(BaseModel):
    """Relationship between two entities."""

    source_id: str
    target_id: str
    relationship_type: RelationshipType
    properties: dict = Field(default_factory=dict)
    source: Optional[str] = None  # Where this info came from
    confidence: float = 1.0
    created_at: datetime = Field(default_factory=datetime.utcnow)


# Schema definition for Neo4j constraints and indexes
GRAPH_SCHEMA = {
    "constraints": [
        "CREATE CONSTRAINT entity_id IF NOT EXISTS FOR (e:Entity) REQUIRE e.id IS UNIQUE",
    ],
    "indexes": [
        "CREATE INDEX entity_name IF NOT EXISTS FOR (e:Entity) ON (e.name)",
        "CREATE INDEX entity_type IF NOT EXISTS FOR (e:Entity) ON (e.entity_type)",
        "CREATE FULLTEXT INDEX entity_search IF NOT EXISTS FOR (e:Entity) ON EACH [e.name, e.description, e.aliases]",
    ],
}
