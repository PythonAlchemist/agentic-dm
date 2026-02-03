"""Combat management endpoints for DM control."""

import logging
from typing import Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from backend.discord.combat_manager import (
    CombatManager,
    CombatConfig,
    TurnResult,
    get_combat_manager,
)

router = APIRouter()
logger = logging.getLogger(__name__)


# ===================
# Request/Response Models
# ===================


class PlayerCombatant(BaseModel):
    """Player combatant for combat."""

    name: str = Field(..., description="Character name")
    initiative_bonus: int = Field(0, description="Initiative modifier")
    hp: int = Field(20, description="Current hit points")
    max_hp: Optional[int] = Field(None, description="Maximum hit points")
    ac: int = Field(15, description="Armor class")
    player_id: Optional[str] = Field(None, description="Player entity ID")
    player_name: Optional[str] = Field(None, description="Player name")
    pc_id: Optional[str] = Field(None, description="PC entity ID")


class NPCCombatant(BaseModel):
    """AI-controlled NPC combatant."""

    name: str = Field(..., description="NPC name")
    npc_id: str = Field(..., description="NPC entity ID for AI control")
    initiative_bonus: Optional[int] = Field(None, description="Override initiative")
    hp: Optional[int] = Field(None, description="Override HP")
    max_hp: Optional[int] = Field(None, description="Override max HP")
    ac: Optional[int] = Field(None, description="Override AC")


class MonsterCombatant(BaseModel):
    """DM-controlled monster combatant."""

    name: str = Field(..., description="Monster name")
    initiative_bonus: int = Field(0, description="Initiative modifier")
    hp: int = Field(10, description="Hit points")
    max_hp: Optional[int] = Field(None, description="Maximum hit points")
    ac: int = Field(12, description="Armor class")


class StartCombatRequest(BaseModel):
    """Request to start combat."""

    players: list[PlayerCombatant] = Field(default_factory=list)
    npcs: list[NPCCombatant] = Field(default_factory=list)
    monsters: list[MonsterCombatant] = Field(default_factory=list)
    auto_npc_turns: bool = Field(True, description="Auto-process NPC turns")


class DamageRequest(BaseModel):
    """Request to apply damage."""

    target: str = Field(..., description="Target name")
    damage: int = Field(..., description="Damage amount")


class HealingRequest(BaseModel):
    """Request to apply healing."""

    target: str = Field(..., description="Target name")
    healing: int = Field(..., description="Healing amount")


class ConditionRequest(BaseModel):
    """Request to add/remove condition."""

    target: str = Field(..., description="Target name")
    condition: str = Field(..., description="Condition name")


class TurnResultResponse(BaseModel):
    """Turn result response."""

    combatant_name: str
    turn_type: str
    round: int
    awaiting_action: bool
    combat_active: bool
    combat_ended_reason: Optional[str] = None
    narration: str
    npc_action: Optional[dict] = None


# ===================
# Combat Control Endpoints
# ===================


@router.post("/combat/start")
async def start_combat(request: StartCombatRequest) -> dict:
    """Start a new combat encounter.

    Players wait for DM input, NPCs act automatically.
    """
    try:
        manager = get_combat_manager()

        # Configure combat manager
        manager.config.auto_npc_turns = request.auto_npc_turns

        # Convert to dicts
        players = [p.model_dump() for p in request.players]
        npcs = [n.model_dump() for n in request.npcs]
        monsters = [m.model_dump() for m in request.monsters] if request.monsters else None

        result = await manager.start_combat(
            players=players,
            npcs=npcs,
            monsters=monsters,
        )

        return result

    except Exception as e:
        logger.error(f"Failed to start combat: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/combat/status")
async def get_combat_status() -> dict:
    """Get current combat status."""
    try:
        manager = get_combat_manager()
        status = manager.get_combat_status()

        if not status:
            return {"active": False, "message": "No combat active"}

        return status

    except Exception as e:
        logger.error(f"Failed to get combat status: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/combat/turn")
async def get_current_turn() -> dict:
    """Get information about the current turn."""
    try:
        manager = get_combat_manager()
        turn = await manager.get_current_turn()

        if not turn:
            return {"active": False, "message": "No combat active"}

        return turn

    except Exception as e:
        logger.error(f"Failed to get current turn: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/combat/turn/process")
async def process_current_turn() -> TurnResultResponse:
    """Process the current turn.

    If it's an NPC turn, executes automatically.
    If it's a player turn, returns info for the DM.
    """
    try:
        manager = get_combat_manager()
        result = await manager.process_current_turn()

        if not result:
            raise HTTPException(status_code=400, detail="No combat active")

        return TurnResultResponse(
            combatant_name=result.combatant_name,
            turn_type=result.turn_type.value,
            round=result.round,
            awaiting_action=result.awaiting_action,
            combat_active=result.combat_active,
            combat_ended_reason=result.combat_ended_reason,
            narration=result.narration,
            npc_action=result.npc_result.model_dump() if result.npc_result else None,
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to process turn: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/combat/turn/end")
async def end_current_turn() -> TurnResultResponse:
    """End the current turn and advance to the next.

    If the next combatant is an NPC, their turn is processed automatically.
    Returns information about the new current turn.
    """
    try:
        manager = get_combat_manager()
        result = await manager.end_turn()

        if not result:
            raise HTTPException(status_code=400, detail="No combat active")

        return TurnResultResponse(
            combatant_name=result.combatant_name,
            turn_type=result.turn_type.value,
            round=result.round,
            awaiting_action=result.awaiting_action,
            combat_active=result.combat_active,
            combat_ended_reason=result.combat_ended_reason,
            narration=result.narration,
            npc_action=result.npc_result.model_dump() if result.npc_result else None,
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to end turn: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/combat/turn/npc-all")
async def process_all_npc_turns() -> list[TurnResultResponse]:
    """Process all consecutive NPC turns.

    Continues until a player or DM-controlled monster turn is reached.
    Returns list of all NPC turn results.
    """
    try:
        manager = get_combat_manager()
        results = await manager.process_all_npc_turns()

        return [
            TurnResultResponse(
                combatant_name=r.combatant_name,
                turn_type=r.turn_type.value,
                round=r.round,
                awaiting_action=r.awaiting_action,
                combat_active=r.combat_active,
                combat_ended_reason=r.combat_ended_reason,
                narration=r.narration,
                npc_action=r.npc_result.model_dump() if r.npc_result else None,
            )
            for r in results
        ]

    except Exception as e:
        logger.error(f"Failed to process NPC turns: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# ===================
# Combat Actions
# ===================


@router.post("/combat/damage")
async def apply_damage(request: DamageRequest) -> dict:
    """Apply damage to a combatant."""
    try:
        manager = get_combat_manager()
        result = manager.apply_damage(request.target, request.damage)

        if "error" in result:
            raise HTTPException(status_code=400, detail=result["error"])

        return result

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to apply damage: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/combat/heal")
async def apply_healing(request: HealingRequest) -> dict:
    """Apply healing to a combatant."""
    try:
        manager = get_combat_manager()
        result = manager.apply_healing(request.target, request.healing)

        if "error" in result:
            raise HTTPException(status_code=400, detail=result["error"])

        return result

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to apply healing: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/combat/condition/add")
async def add_condition(request: ConditionRequest) -> dict:
    """Add a condition to a combatant."""
    try:
        manager = get_combat_manager()
        result = manager.add_condition(request.target, request.condition)

        if "error" in result:
            raise HTTPException(status_code=400, detail=result["error"])

        return result

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to add condition: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/combat/condition/remove")
async def remove_condition(request: ConditionRequest) -> dict:
    """Remove a condition from a combatant."""
    try:
        manager = get_combat_manager()
        result = manager.remove_condition(request.target, request.condition)

        if "error" in result:
            raise HTTPException(status_code=400, detail=result["error"])

        return result

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to remove condition: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/combat/end")
async def end_combat() -> dict:
    """End the current combat and get summary."""
    try:
        manager = get_combat_manager()
        summary = await manager.end_combat()

        return summary

    except Exception as e:
        logger.error(f"Failed to end combat: {e}")
        raise HTTPException(status_code=500, detail=str(e))
