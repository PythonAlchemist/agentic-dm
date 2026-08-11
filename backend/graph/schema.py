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
    SHOP = "SHOP"  # Shops and merchants


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
    COMPLETED = "COMPLETED"
    OBJECTIVE_AT = "OBJECTIVE_AT"

    # Narrative layer
    SEEKS = "SEEKS"  # Agent -> what it wants; carries a free-text `motive`
    OPPOSES = "OPPOSES"  # Agent -> goal it works against (distinct from HOSTILE_TO)
    IDENTITY_OF = "IDENTITY_OF"  # Persona -> persona; carries `nature`
    RESOLVES_TO = "RESOLVES_TO"  # Canon fan-out a table's draw collapses
    PREREQUISITE_OF = "PREREQUISITE_OF"  # Hard gate
    THREATENS = "THREATENS"  # Standing danger

    # Combat/Events
    KILLED = "KILLED"
    PARTICIPATED_IN = "PARTICIPATED_IN"
    OCCURRED_AT = "OCCURRED_AT"
    OCCURRED_IN = "OCCURRED_IN"

    # Character attributes
    HAS_CLASS = "HAS_CLASS"  # PC/NPC -> Class
    HAS_RACE = "HAS_RACE"  # PC/NPC -> Race
    HAS_SUBCLASS = "HAS_SUBCLASS"  # PC/NPC -> Subclass
    WIELDS = "WIELDS"  # PC/NPC -> Weapon/Item (equipped)
    SERVES = "SERVES"  # NPC -> NPC/Faction (loyalty/service)
    RELATED_TO = "RELATED_TO"  # Family/blood relation
    TRAVELED_TO = "TRAVELED_TO"  # Character -> Location (visited)

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


class Layer(str, Enum):
    """A surface of the graph. Edges carry exactly one, or none."""

    SPATIAL = "spatial"
    SOCIAL = "social"
    NARRATIVE = "narrative"


# Every RelationshipType maps to a layer or explicitly to None. None means "not a
# surface": plane-linking, character-sheet, and runtime edges. A partial map would
# silently mis-count intersection queries, so tests assert this is total.
LAYER_MAP: dict[RelationshipType, Layer | None] = {
    # Spatial
    RelationshipType.LOCATED_IN: Layer.SPATIAL,
    RelationshipType.CONTAINS: Layer.SPATIAL,
    RelationshipType.CONNECTED_TO: Layer.SPATIAL,
    RelationshipType.TRAVELED_TO: Layer.SPATIAL,
    # Social
    RelationshipType.KNOWS: Layer.SOCIAL,
    RelationshipType.ALLIED_WITH: Layer.SOCIAL,
    RelationshipType.HOSTILE_TO: Layer.SOCIAL,
    RelationshipType.ENEMY_OF: Layer.SOCIAL,
    RelationshipType.MEMBER_OF: Layer.SOCIAL,
    RelationshipType.SERVES: Layer.SOCIAL,
    RelationshipType.RELATED_TO: Layer.SOCIAL,
    RelationshipType.OWNS: Layer.SOCIAL,
    RelationshipType.GUARDS: Layer.SOCIAL,
    RelationshipType.WIELDS: Layer.SOCIAL,
    # Narrative
    RelationshipType.SEEKS: Layer.NARRATIVE,
    RelationshipType.OPPOSES: Layer.NARRATIVE,
    RelationshipType.RESOLVES_TO: Layer.NARRATIVE,
    RelationshipType.PREREQUISITE_OF: Layer.NARRATIVE,
    RelationshipType.IDENTITY_OF: Layer.NARRATIVE,
    RelationshipType.THREATENS: Layer.NARRATIVE,
    RelationshipType.GAVE_QUEST: Layer.NARRATIVE,
    RelationshipType.COMPLETED: Layer.NARRATIVE,
    RelationshipType.OBJECTIVE_AT: Layer.NARRATIVE,
    # Structural: plane-linking, character sheet, runtime, campaign history
    RelationshipType.INSTANCE_OF: None,
    RelationshipType.BELONGS_TO: None,
    RelationshipType.PLAYS_AS: None,
    RelationshipType.ATTENDED: None,
    RelationshipType.HAS_CLASS: None,
    RelationshipType.HAS_RACE: None,
    RelationshipType.HAS_SUBCLASS: None,
    RelationshipType.CONTROLLED_BY: None,
    RelationshipType.IN_COMBAT_WITH: None,
    RelationshipType.LAST_SPOKE_TO: None,
    RelationshipType.KILLED: None,
    RelationshipType.PARTICIPATED_IN: None,
    RelationshipType.OCCURRED_AT: None,
    RelationshipType.OCCURRED_IN: None,
}

# The entity types a source book can describe. Campaign-runtime types (PC, PLAYER,
# SESSION, CAMPAIGN) and mechanical ones (CLASS, RACE, RULE, SPELL) are deliberately
# excluded: canon extraction that proposes them is miscategorizing, not discovering.
CANON_ENTITY_TYPES: frozenset[EntityType] = frozenset({
    EntityType.LOCATION,
    EntityType.NPC,
    EntityType.MONSTER,
    EntityType.FACTION,
    EntityType.ITEM,
    EntityType.LORE,
    EntityType.EVENT,
    EntityType.QUEST,
    EntityType.SETTING,
})

# A directional gloss for every relationship type offered to the extraction prompt
# (i.e. every type in a layer vocabulary -- see `layer_vocabulary`). A bare type
# name like OWNS does not say which endpoint is the owner; the gloss does. Types
# outside the three extraction layers (structural/runtime edges) are not glossed --
# the extractor never offers them, so there is nothing to disambiguate.
RELATIONSHIP_GLOSS: dict[RelationshipType, str] = {
    RelationshipType.CONNECTED_TO: "A CONNECTED_TO B - a route or passage joins A and B.",
    RelationshipType.CONTAINS: (
        "A CONTAINS B - B sits inside A. A is the larger, containing place."
    ),
    RelationshipType.LOCATED_IN: (
        "A LOCATED_IN B - A sits inside B. B is the larger, containing place."
    ),
    RelationshipType.TRAVELED_TO: "A TRAVELED_TO B - A journeyed to B.",
    RelationshipType.ALLIED_WITH: "A ALLIED_WITH B - A and B are allies.",
    RelationshipType.ENEMY_OF: "A ENEMY_OF B - A is a standing enemy of B.",
    RelationshipType.GUARDS: (
        "A GUARDS B - A keeps B confined, protected, or watched over."
    ),
    RelationshipType.HOSTILE_TO: "A HOSTILE_TO B - A is presently hostile toward B.",
    RelationshipType.KNOWS: "A KNOWS B - A is acquainted with B.",
    RelationshipType.MEMBER_OF: (
        "A MEMBER_OF B - A belongs to the group B. B is the group."
    ),
    RelationshipType.OWNS: (
        "A OWNS B - A is the owner or proprietor of B. A is the owner."
    ),
    RelationshipType.RELATED_TO: (
        "A RELATED_TO B - A and B are kin: parent, child, sibling, cousin, uncle, "
        "nephew. Family ties ONLY."
    ),
    RelationshipType.SERVES: (
        "A SERVES B - A works for or is subordinate to B. B is the master."
    ),
    RelationshipType.WIELDS: "A WIELDS B - A carries or uses the item B.",
    RelationshipType.COMPLETED: "A COMPLETED B - A finished the quest B.",
    RelationshipType.GAVE_QUEST: (
        "A GAVE_QUEST B - A asks the party to undertake quest B. A is the giver, "
        "B is the quest."
    ),
    RelationshipType.IDENTITY_OF: (
        "A IDENTITY_OF B - A and B are the SAME being under two names or two lives: "
        "a reincarnation, a soul reborn, a secret alias. NOT for family relationships."
    ),
    RelationshipType.OBJECTIVE_AT: (
        "A OBJECTIVE_AT B - quest A is pursued or completed at place B."
    ),
    RelationshipType.OPPOSES: "A OPPOSES B - A works against B's goals.",
    RelationshipType.PREREQUISITE_OF: "A PREREQUISITE_OF B - A must happen before B can.",
    RelationshipType.RESOLVES_TO: "A RESOLVES_TO B - the outcome of A is B.",
    RelationshipType.SEEKS: "A SEEKS B - A wants to obtain, reach, or accomplish B.",
    RelationshipType.THREATENS: "A THREATENS B - A endangers B.",
}

# Shorthands for the domain/range table below. Named for what they have in
# common rather than enumerated at each use, so widening "what can act" is one
# edit rather than twelve.
_ANIMATE: frozenset[EntityType] = frozenset({EntityType.NPC, EntityType.MONSTER})
# A FACTION acts, but has no body: it can ally, own and threaten, but cannot be
# wielded, contained, or carry a family tie.
_AGENT: frozenset[EntityType] = _ANIMATE | {EntityType.FACTION}
_PHYSICAL: frozenset[EntityType] = _ANIMATE | {EntityType.ITEM, EntityType.LOCATION}
# What one thing can sit inside. A chest is not a place, but a coin is inside it,
# and `LOCATION CONTAINS ITEM` was already legal -- refusing the item container
# would say a coin may sit in a room but not in the chest standing in that room.
# Measured on chapter 4: restricting containers to LOCATION rejected 19 real
# treasure facts (`four wooden chests CONTAINS 500 pp`) and 18 derived structural
# edges whose keyed area the extractor happened to type ITEM.
_CONTAINER: frozenset[EntityType] = frozenset({EntityType.LOCATION, EntityType.ITEM})

# What each relationship's endpoints may be: `(domain, range)`, the domain
# constraining the SOURCE and the range the TARGET. This makes the direction the
# gloss states machine-checkable -- "A OWNS B - A is the owner" already says an
# owner is an agent and a possession is not -- at no cost in LLM calls or
# external sources.
#
# Motivating measurement: a hand read of 30 chapter-4 extracted edges found 16
# false, of which NINE are impossible by type rather than by fact, e.g.
# `Chapel -LOCATED_IN-> Donavich` (a location inside a priest) and
# `Guards' Post -GUARDS-> Skeleton` (a room standing watch).
#
# Only the types the extractor is offered are constrained -- i.e. exactly the
# types in a layer vocabulary, the same set RELATIONSHIP_GLOSS covers. Runtime
# and character-sheet edges are not proposed by any extractor, so a constraint
# on them would assert an ontology nothing can violate. Tests assert this
# totality by iterating Layer and layer_vocabulary, so a type added to LAYER_MAP
# fails until it is given a domain and range.
#
# Two entries look wrong until checked against the data:
# - RELATED_TO is NPC->NPC only. Its gloss is "kin ... Family ties ONLY", and
#   widening it to _AGENT would blunt the IDENTITY_OF / RELATED_TO contrast the
#   glosses were written to fix.
# - RESOLVES_TO has ITEM in its domain. Not a slip: the Tarokka reading resolves
#   an item to a place, and `tome-of-strahd RESOLVES_TO church-of-barovia` is a
#   real golden edge.
RELATIONSHIP_DOMAIN_RANGE: dict[
    RelationshipType, tuple[frozenset[EntityType], frozenset[EntityType]]
] = {
    # Spatial
    RelationshipType.CONNECTED_TO: (
        frozenset({EntityType.LOCATION}),
        frozenset({EntityType.LOCATION}),
    ),
    RelationshipType.CONTAINS: (_CONTAINER, _PHYSICAL),
    RelationshipType.LOCATED_IN: (_PHYSICAL | {EntityType.FACTION}, _CONTAINER),
    RelationshipType.TRAVELED_TO: (_AGENT, frozenset({EntityType.LOCATION})),
    # Social
    RelationshipType.ALLIED_WITH: (_AGENT, _AGENT),
    RelationshipType.ENEMY_OF: (_AGENT, _AGENT),
    RelationshipType.GUARDS: (_AGENT, _PHYSICAL),
    RelationshipType.HOSTILE_TO: (_AGENT, _AGENT),
    RelationshipType.KNOWS: (_ANIMATE, _ANIMATE),
    RelationshipType.MEMBER_OF: (_ANIMATE, frozenset({EntityType.FACTION})),
    RelationshipType.OWNS: (_AGENT, frozenset({EntityType.ITEM, EntityType.LOCATION})),
    RelationshipType.RELATED_TO: (
        frozenset({EntityType.NPC}),
        frozenset({EntityType.NPC}),
    ),
    RelationshipType.SERVES: (_ANIMATE, _AGENT),
    RelationshipType.WIELDS: (_ANIMATE, frozenset({EntityType.ITEM})),
    # Narrative
    RelationshipType.COMPLETED: (_AGENT, frozenset({EntityType.QUEST})),
    RelationshipType.GAVE_QUEST: (_AGENT, frozenset({EntityType.QUEST})),
    RelationshipType.IDENTITY_OF: (_ANIMATE, _ANIMATE),
    RelationshipType.OBJECTIVE_AT: (
        frozenset({EntityType.QUEST}),
        frozenset({EntityType.LOCATION}),
    ),
    RelationshipType.OPPOSES: (_AGENT, _AGENT),
    RelationshipType.PREREQUISITE_OF: (
        frozenset({EntityType.QUEST, EntityType.EVENT}),
        frozenset({EntityType.QUEST, EntityType.EVENT}),
    ),
    RelationshipType.RESOLVES_TO: (
        frozenset({EntityType.ITEM, EntityType.QUEST, EntityType.EVENT}),
        frozenset({EntityType.LOCATION, EntityType.NPC, EntityType.ITEM}),
    ),
    RelationshipType.SEEKS: (
        _AGENT,
        _PHYSICAL | {EntityType.QUEST, EntityType.LORE},
    ),
    RelationshipType.THREATENS: (_AGENT, _PHYSICAL | {EntityType.FACTION}),
}

# Campaign edges of these types SHADOW canon edges of the same type from the same
# source, rather than adding to them. This is the Tarokka collapse: canon fans out to
# ten candidate sites, a table's draw resolves it to one.
RESOLVABLE_TYPES: set[RelationshipType] = {RelationshipType.RESOLVES_TO}


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
    # World & Setting
    setting: Optional[str] = None          # e.g., "Forgotten Realms", "Eberron"
    world_description: Optional[str] = None  # Broader world/setting description
    theme: Optional[str] = None            # e.g., "dark fantasy", "political intrigue"
    # Rules & Mechanics
    rule_system: str = "D&D 5e"            # e.g., "D&D 5e", "D&D 2024"
    level_range: Optional[str] = None      # e.g., "1-10", "3-15"
    house_rules: Optional[str] = None      # Freeform text for custom rules
    allowed_sources: Optional[str] = None  # Sourcebooks allowed
    # Story Context
    premise: Optional[str] = None          # Campaign synopsis/premise
    current_story_arc: Optional[str] = None  # Where the party is in the narrative
    dm_notes: Optional[str] = None         # Private DM notes
    # Existing
    start_date: Optional[datetime] = None
    status: str = "active"                 # active, paused, completed


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
        # Canon/campaign resolver indexes
        "CREATE INDEX entity_plane IF NOT EXISTS FOR (e:Entity) ON (e.plane)",
        "CREATE INDEX entity_canon_id IF NOT EXISTS FOR (e:Entity) ON (e.canon_id)",
    ],
}
