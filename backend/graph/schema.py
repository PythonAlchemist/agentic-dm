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


class LocationSubtype(str, Enum):
    """Where a LOCATION sits in the spatial hierarchy.

    An ADDITIONAL label, never a replacement: `:LOCATION` stays on every place,
    because it is what makes "every place in the book" a one-word query. The
    subtype narrows it -- `MATCH (n:AREA)` is every room.

    A place wears at most one of these. They are rungs of a single ladder, not
    orthogonal facets, so `:SITE:SETTLEMENT` would be a contradiction rather
    than two readings the way a disputed `:NPC:MONSTER` is.

    SITE and AREA are DERIVED from the book's own key convention -- see
    `KEYED_HEADING` -- and are never authored by hand. REGION, SETTLEMENT and
    WILD cannot be derived from anything the document says about itself and are
    authored, roughly fifteen entries for a whole book. A place with neither
    stays plain `:LOCATION`: there is no default, because an unclassified place
    must be visibly unclassified rather than quietly filed somewhere plausible.
    """

    REGION = "REGION"  # A land or domain -- Barovia
    SETTLEMENT = "SETTLEMENT"  # Village, town, city
    SITE = "SITE"  # A discrete building or landmark -- a top-level key
    AREA = "AREA"  # A room or sub-area within a site -- a suffixed key
    WILD = "WILD"  # Wilderness, roads, passes


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
    MENTIONED_IN = "MENTIONED_IN"  # Canon entity -> :Chapter it appears in

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
    # Provenance, not a surface: it says WHERE a canon entity is written about,
    # which is deterministic and unfalsifiable, and says nothing about the world.
    RelationshipType.MENTIONED_IN: None,
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

# The two rungs the book's own key convention decides -- an unsuffixed key is a
# building, a suffixed one is a room inside it. Everything else is hand-authored.
# Split here rather than at either use site so the seed's validator and the
# writer's deriver cannot disagree about which half owns a rung.
DERIVED_LOCATION_SUBTYPES: frozenset[LocationSubtype] = frozenset({
    LocationSubtype.SITE,
    LocationSubtype.AREA,
})

AUTHORED_LOCATION_SUBTYPES: frozenset[LocationSubtype] = (
    frozenset(LocationSubtype) - DERIVED_LOCATION_SUBTYPES
)

# The one item label: an ADDITIONAL label on the handful of ITEMs the campaign
# turns on. `MATCH (n:Artifact)` answers "where are the artifacts", which a DM
# asks constantly and which a flat :ITEM -- Sunsword beside oil lamp and
# tinderbox -- cannot answer at all.
#
# NOT A RUNG, and the distinction is load-bearing. A LocationSubtype is a
# position on a ladder, so writing one clears the others; this is orthogonal to
# that ladder and to any item label that might come later, so nothing
# supersedes it and it supersedes nothing -- least of all the :ITEM it narrows.
#
# HAND-AUTHORED, in `canon/seeds/location-subtypes.yaml` beside the location
# rungs. No convention in the text marks an artifact the way a suffixed key
# marks a room, so there is nothing to derive it from and nothing infers it
# from a name. An item with no authored entry stays plain :ITEM: there is no
# `:mundane`, because mundane is the ABSENCE of significance and the honest
# encoding of an absence is no label.
#
# A bare string rather than a one-member enum, and cased like `:Entity` and
# `:Chapter` rather than like an extracted type, because it is neither a
# taxonomy nor something the extractor proposes. A second item label is a
# design decision, not an entry to append here.
ARTIFACT_LABEL = "Artifact"

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

# Pairs of relationship types that CANNOT both hold between the same ORDERED pair
# of entities. Exclusion is about contradiction, not redundancy or rarity: the bar
# is that the contradiction can be stated in one sentence.
#
# Motivating measurement: the live chapter-3 graph holds both
# `Ireena -IDENTITY_OF-> Tatyana` and `Ireena -RELATED_TO-> Tatyana`. One says they
# are one soul, the other that they are kin. Nothing noticed, because
# RELATIONSHIP_DOMAIN_RANGE checks each edge in isolation and both are legal alone.
#
# ORDERED is the whole of the second entry. `Church CONTAINS Undercroft` beside
# `Undercroft LOCATED_IN Church` is the ordinary inverse pair -- the derived
# structural layer emits exactly that, and it is the cleanest layer in the graph.
# Only the SAME direction contradicts: A cannot both hold B and sit inside B.
#
# Deliberately NOT here, and why the table is short:
# - KNOWS / ENEMY_OF -- both are true of plenty of people.
# - ALLIED_WITH / HOSTILE_TO -- a betrayal arc makes both true of one ordered pair
#   at different points of one book, and these edges carry no time index. Merely
#   unusual is not exclusive.
MUTUALLY_EXCLUSIVE: frozenset[frozenset[RelationshipType]] = frozenset(
    {
        # One being under two names cannot also be its own kin.
        frozenset({RelationshipType.IDENTITY_OF, RelationshipType.RELATED_TO}),
        # Mutual containment: A holds B and A is inside B.
        frozenset({RelationshipType.CONTAINS, RelationshipType.LOCATED_IN}),
    }
)

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
        # A chapter is identified by its slug and nothing else, and every canon
        # entity MERGEs its MENTIONED_IN edge against it -- a second node for one
        # slug would split a chapter's appearances in two.
        "CREATE CONSTRAINT chapter_slug IF NOT EXISTS FOR (c:Chapter) REQUIRE c.slug IS UNIQUE",
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
