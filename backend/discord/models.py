"""Data models for NPC Discord integration."""

from datetime import datetime
from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field


class NPCTriggerType(str, Enum):
    """Types of triggers that activate an NPC."""

    DIRECT_MENTION = "direct_mention"  # @mention of the bot
    NAME_REFERENCE = "name_reference"  # NPC name in message
    COMBAT_TURN = "combat_turn"  # NPC's turn in combat
    DM_COMMAND = "dm_command"  # DM command to control NPC
    PROXIMITY = "proximity"  # Future: location-based
    SCHEDULED = "scheduled"  # Future: scheduled events


class VoiceConfig(BaseModel):
    """Voice synthesis configuration for future TTS."""

    voice_id: Optional[str] = None
    pitch: float = 1.0
    speed: float = 1.0
    accent_notes: Optional[str] = None
    enabled: bool = False


class NPCDiscordConfig(BaseModel):
    """Discord bot configuration for an NPC."""

    npc_id: str
    discord_bot_token: str
    discord_application_id: str
    discord_guild_ids: list[str] = Field(default_factory=list)
    display_name: Optional[str] = None
    avatar_url: Optional[str] = None
    status_message: Optional[str] = None
    active: bool = True
    voice_config: Optional[VoiceConfig] = None
    created_at: datetime = Field(default_factory=datetime.utcnow)


class NPCStatBlock(BaseModel):
    """D&D 5e stat block for NPC combat."""

    # Core Stats
    armor_class: int = 10
    hit_points: int = 10
    max_hit_points: int = 10
    speed: int = 30

    # Ability Scores
    strength: int = 10
    dexterity: int = 10
    constitution: int = 10
    intelligence: int = 10
    wisdom: int = 10
    charisma: int = 10

    # Combat
    initiative_bonus: int = 0
    proficiency_bonus: int = 2

    # Attacks: [{"name": "Longsword", "bonus": 5, "damage": "1d8+3", "type": "slashing"}]
    attacks: list[dict] = Field(default_factory=list)

    # Special abilities: [{"name": "Multiattack", "description": "Makes two attacks"}]
    special_abilities: list[dict] = Field(default_factory=list)

    # Spells: {"slots": {1: 4, 2: 3}, "known": ["fireball", "shield"]}
    spells: Optional[dict] = None

    # Detailed spellcasting (for proper caster NPCs)
    spell_save_dc: int = 0
    spell_attack_bonus: int = 0
    cantrips: list[dict] = Field(default_factory=list)  # At-will spells
    spell_slots: dict = Field(default_factory=dict)  # {"1st": 4, "2nd": 2}
    spells_known: list[dict] = Field(default_factory=list)  # Full spell details

    # Conditions
    resistances: list[str] = Field(default_factory=list)
    immunities: list[str] = Field(default_factory=list)
    vulnerabilities: list[str] = Field(default_factory=list)
    condition_immunities: list[str] = Field(default_factory=list)

    # CR for XP calculation
    challenge_rating: float = 1.0


class NPCPersonality(BaseModel):
    """Extended personality model for consistent NPC behavior."""

    # Core traits (used in prompts)
    personality_traits: list[str] = Field(default_factory=list)
    ideals: list[str] = Field(default_factory=list)
    bonds: list[str] = Field(default_factory=list)
    flaws: list[str] = Field(default_factory=list)

    # Behavioral modifiers (0-1 scale)
    aggression_level: float = 0.5
    talkativeness: float = 0.5
    helpfulness: float = 0.5

    # Combat style
    combat_style: str = "balanced"
    preferred_targets: list[str] = Field(default_factory=list)
    retreat_threshold: float = 0.25

    # Speech patterns
    speech_style: str = "normal"
    catchphrases: list[str] = Field(default_factory=list)
    verbal_tics: list[str] = Field(default_factory=list)

    # Memory/knowledge
    topics_of_interest: list[str] = Field(default_factory=list)
    secrets: list[str] = Field(default_factory=list)
    knowledge_domains: list[str] = Field(default_factory=list)


class NPCFaction(str, Enum):
    """Default faction for an NPC in combat."""

    HOSTILE = "hostile"  # Fights against players (default)
    FRIENDLY = "friendly"  # Fights alongside players
    NEUTRAL = "neutral"  # Won't attack unless provoked


class NPCFullProfile(BaseModel):
    """Complete NPC profile combining all aspects."""

    # Identity
    entity_id: str
    name: str
    race: str = "human"
    role: str = "commoner"
    description: Optional[str] = None
    aliases: list[str] = Field(default_factory=list)

    # Discord
    discord_config: Optional[NPCDiscordConfig] = None

    # Game Stats
    stat_block: NPCStatBlock = Field(default_factory=NPCStatBlock)

    # Personality
    personality: NPCPersonality = Field(default_factory=NPCPersonality)

    # Combat Faction
    default_faction: NPCFaction = Field(
        default=NPCFaction.HOSTILE,
        description="Default faction when added to combat without explicit is_friendly"
    )

    # State
    current_location_id: Optional[str] = None
    current_hp: Optional[int] = None
    conditions: list[str] = Field(default_factory=list)

    # Relationships (cached from graph)
    allied_with: list[str] = Field(default_factory=list)
    hostile_to: list[str] = Field(default_factory=list)

    # Activity
    last_interaction: Optional[datetime] = None
    interaction_count: int = 0
