"""Combat-related models for NPC actions and results."""

from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field


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
