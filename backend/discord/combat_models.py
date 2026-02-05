"""Combat-related models for NPC actions and results."""

from enum import Enum
from typing import Optional
from dataclasses import dataclass, field

from pydantic import BaseModel, Field


# ===================
# Combat Memory - Tracks events for realistic NPC reactions
# ===================


@dataclass
class CombatEvent:
    """A single event that happened in combat."""

    round: int
    description: str
    event_type: str  # "damage_taken", "damage_dealt", "ally_down", "spell_used", etc.
    actor: Optional[str] = None
    target: Optional[str] = None
    amount: Optional[int] = None


@dataclass
class CombatantState:
    """Current state of a combatant from an NPC's perspective."""

    name: str
    hp: int
    max_hp: int
    ac: int
    is_ally: bool
    distance: str = "nearby"  # Distance string, e.g. "30ft" or "melee"
    distance_ft: Optional[int] = None  # Actual distance in feet, if known
    conditions: list[str] = field(default_factory=list)
    threat_level: str = "medium"  # "low", "medium", "high"
    damage_to_me: int = 0  # How much they've hurt this NPC


class CombatMemory:
    """
    Lightweight memory for a single combat encounter.

    Tracks only what matters for tactical decisions:
    - Recent events (rolling window of 5)
    - Who hurt me and how much
    - Spells/abilities I've used
    - Allies who have fallen
    """

    def __init__(self, npc_name: str):
        self.npc_name = npc_name
        self.events: list[CombatEvent] = []
        self.damage_taken_from: dict[str, int] = {}  # name -> total damage
        self.damage_dealt_to: dict[str, int] = {}
        self.spells_used: list[str] = []
        self.slots_used: dict[str, int] = {}  # "1st" -> count used
        self.allies_fallen: list[str] = []
        self.current_round: int = 1

    def record_damage_taken(self, attacker: str, damage: int, weapon: str, round: int):
        """Record damage this NPC took."""
        self.damage_taken_from[attacker] = self.damage_taken_from.get(attacker, 0) + damage
        self.events.append(CombatEvent(
            round=round,
            description=f"{attacker} hit you with {weapon} for {damage} damage",
            event_type="damage_taken",
            actor=attacker,
            target=self.npc_name,
            amount=damage,
        ))
        self._trim_events()

    def record_damage_dealt(self, target: str, damage: int, weapon: str, round: int):
        """Record damage this NPC dealt."""
        self.damage_dealt_to[target] = self.damage_dealt_to.get(target, 0) + damage
        self.events.append(CombatEvent(
            round=round,
            description=f"You hit {target} with {weapon} for {damage} damage",
            event_type="damage_dealt",
            actor=self.npc_name,
            target=target,
            amount=damage,
        ))
        self._trim_events()

    def record_miss(self, target: str, weapon: str, round: int, is_attacker: bool = True):
        """Record a missed attack."""
        if is_attacker:
            desc = f"Your {weapon} missed {target}"
        else:
            desc = f"{target}'s attack missed you"
        self.events.append(CombatEvent(
            round=round,
            description=desc,
            event_type="miss",
        ))
        self._trim_events()

    def record_spell_used(self, spell_name: str, level: Optional[str], round: int):
        """Record a spell cast."""
        self.spells_used.append(spell_name)
        if level and level != "cantrip":
            self.slots_used[level] = self.slots_used.get(level, 0) + 1

    def record_ally_down(self, ally_name: str, killer: str, round: int):
        """Record an ally falling."""
        self.allies_fallen.append(ally_name)
        self.events.append(CombatEvent(
            round=round,
            description=f"Your ally {ally_name} was killed by {killer}",
            event_type="ally_down",
            actor=killer,
            target=ally_name,
        ))
        self._trim_events()

    def record_enemy_down(self, enemy_name: str, round: int):
        """Record an enemy falling."""
        self.events.append(CombatEvent(
            round=round,
            description=f"{enemy_name} has fallen!",
            event_type="enemy_down",
            target=enemy_name,
        ))
        self._trim_events()

    def get_grudge_target(self) -> Optional[str]:
        """Who has hurt this NPC the most?"""
        if not self.damage_taken_from:
            return None
        return max(self.damage_taken_from, key=self.damage_taken_from.get)

    def get_remaining_slots(self, total_slots: dict[str, int]) -> dict[str, int]:
        """Calculate remaining spell slots."""
        remaining = {}
        for level, total in total_slots.items():
            used = self.slots_used.get(level, 0)
            remaining[level] = max(0, total - used)
        return remaining

    def get_events_summary(self) -> str:
        """Get a brief summary of recent events."""
        if not self.events:
            return "Combat just started."
        return "\n".join(f"- {e.description}" for e in self.events[-5:])

    def _trim_events(self):
        """Keep only the most recent events."""
        self.events = self.events[-5:]


class CombatActionType(str, Enum):
    """Types of combat actions an NPC can take."""

    ATTACK = "attack"
    CAST_SPELL = "cast_spell"
    USE_ABILITY = "use_ability"
    MOVE = "move"
    DASH = "dash"
    DODGE = "dodge"
    DISENGAGE = "disengage"
    HELP = "help"
    HIDE = "hide"
    READY = "ready"
    USE_ITEM = "use_item"
    MULTIATTACK = "multiattack"
    FLEE = "flee"
    SURRENDER = "surrender"
    DIALOGUE = "dialogue"


class NPCCombatDecision(BaseModel):
    """A decision made by an NPC during combat."""

    npc_id: str
    round: int

    # Action
    action_type: CombatActionType
    action_name: Optional[str] = None

    # Target
    target_name: Optional[str] = None
    target_id: Optional[str] = None

    # Movement
    movement_description: Optional[str] = None

    # Reasoning (for transparency)
    reasoning: str

    # Dialogue (if any)
    combat_dialogue: Optional[str] = None

    # Dice rolls to make
    # [{"type": "attack", "expression": "1d20+5"}, {"type": "damage", "expression": "1d8+3"}]
    rolls_needed: list[dict] = Field(default_factory=list)


class NPCCombatResult(BaseModel):
    """Result of an NPC combat action."""

    npc_id: str
    npc_name: str

    # Action taken
    action: NPCCombatDecision

    # Rolls made
    attack_roll: Optional[dict] = None
    damage_roll: Optional[dict] = None

    # Outcome
    hit: Optional[bool] = None
    damage_dealt: Optional[int] = None
    target_new_hp: Optional[int] = None

    # Narration
    narration: str

    # State changes
    conditions_applied: list[str] = Field(default_factory=list)
