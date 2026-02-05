"""Knowledge graph schema definitions for D&D campaigns."""

from enum import Enum
from typing import Optional
from datetime import datetime

from pydantic import BaseModel, Field


class EntityType(str, Enum):
    """Types of entities in the campaign knowledge graph."""

    PLAYER = "PLAYER"  # Real human players
    PC = "PC"  # Player Characters
    NPC = "NPC"  # Non-Player Characters
    LOCATION = "LOCATION"  # Places
    ITEM = "ITEM"  # Objects, weapons, artifacts
    MONSTER = "MONSTER"  # Creatures and enemies
    FACTION = "FACTION"  # Organizations
    QUEST = "QUEST"  # Quests and objectives
    EVENT = "EVENT"  # Significant happenings
    SESSION = "SESSION"  # Game session metadata
    CAMPAIGN = "CAMPAIGN"  # Campaign container
    SPELL = "SPELL"  # Spell definitions
    CLASS = "CLASS"  # Character classes
    RACE = "RACE"  # Character races
    RULE = "RULE"  # Game rules
    LORE = "LORE"  # World lore
    SETTING = "SETTING"  # Campaign settings


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

    # Player/Campaign
    PLAYS_AS = "PLAYS_AS"  # Player -> PC
    ATTENDED = "ATTENDED"  # Player -> Session
    BELONGS_TO = "BELONGS_TO"  # Player/PC -> Campaign
    ENEMY_OF = "ENEMY_OF"  # General enmity

    # NPC Discord interactions
    CONTROLLED_BY = "CONTROLLED_BY"  # Discord bot -> NPC
    IN_COMBAT_WITH = "IN_COMBAT_WITH"  # NPC <-> Combatant
    LAST_SPOKE_TO = "LAST_SPOKE_TO"  # NPC -> PC/Player


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


class PlayerEntity(Entity):
    """Real-world player entity."""

    entity_type: EntityType = EntityType.PLAYER
    email: Optional[str] = None
    discord_id: Optional[str] = None
    joined_at: Optional[datetime] = None
    active_pc_id: Optional[str] = None  # Current active character
    notes: Optional[str] = None


class PCEntity(Entity):
    """Player Character entity."""

    entity_type: EntityType = EntityType.PC
    player_id: Optional[str] = None  # Link to Player entity
    player_name: Optional[str] = None  # Denormalized for convenience
    character_class: Optional[str] = None
    level: int = 1
    hp: Optional[int] = None
    max_hp: Optional[int] = None
    initiative_bonus: int = 0
    status: str = "alive"  # alive, dead, unknown


class NPCEntity(Entity):
    """Non-Player Character entity."""

    entity_type: EntityType = EntityType.NPC
    disposition: str = "neutral"  # friendly, neutral, hostile
    importance: str = "minor"  # major, minor, background
    race: Optional[str] = None
    role: Optional[str] = None

    # Discord integration
    discord_bot_token: Optional[str] = None
    discord_application_id: Optional[str] = None
    discord_guild_ids: list[str] = Field(default_factory=list)
    discord_display_name: Optional[str] = None
    discord_active: bool = False

    # Combat stats (stored as JSON string in graph)
    stat_block: Optional[str] = None

    # Personality config (stored as JSON string in graph)
    personality_config: Optional[str] = None

    # Runtime state
    current_hp: Optional[int] = None
    current_conditions: list[str] = Field(default_factory=list)
    current_location_id: Optional[str] = None


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


class CampaignEntity(Entity):
    """Campaign entity - container for a full campaign."""

    entity_type: EntityType = EntityType.CAMPAIGN
    setting: Optional[str] = None  # e.g., "Forgotten Realms"
    start_date: Optional[datetime] = None
    status: str = "active"  # active, paused, completed


class SessionEntity(Entity):
    """Session entity for tracking game sessions."""

    entity_type: EntityType = EntityType.SESSION
    session_number: int
    campaign_id: Optional[str] = None
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
        # NPC Discord indexes
        "CREATE INDEX npc_discord_active IF NOT EXISTS FOR (e:Entity) ON (e.discord_active)",
        "CREATE INDEX npc_discord_app_id IF NOT EXISTS FOR (e:Entity) ON (e.discord_application_id)",
    ],
}
