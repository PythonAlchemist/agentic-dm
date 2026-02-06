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
from backend.discord.npc_registry import NPCRegistry

router = APIRouter()
logger = logging.getLogger(__name__)

# Registry for NPC lookups
_npc_registry: Optional[NPCRegistry] = None


def get_npc_registry() -> NPCRegistry:
    """Get NPC registry singleton."""
    global _npc_registry
    if _npc_registry is None:
        _npc_registry = NPCRegistry()
    return _npc_registry


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
    is_friendly: bool = Field(False, description="True if NPC fights alongside players")


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


class NPCTurnResultItem(BaseModel):
    """Individual NPC turn result."""

    combatant_name: str
    turn_type: str
    round: int
    narration: str
    npc_action: Optional[dict] = None


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
    npc_turn_results: list[NPCTurnResultItem] = Field(default_factory=list)


# ===================
# NPC Lookup Endpoints
# ===================


class NPCSearchResult(BaseModel):
    """NPC available for combat."""

    entity_id: str
    name: str
    race: str
    role: str
    hp: int
    max_hp: int
    ac: int
    initiative_bonus: int
    challenge_rating: float
    description: Optional[str] = None


@router.get("/combat/npcs")
async def search_npcs(
    query: Optional[str] = None,
    hostile_only: bool = False,
    limit: int = 20,
) -> list[NPCSearchResult]:
    """Search for available NPCs to add to combat.

    Args:
        query: Optional search string for name/description.
        hostile_only: Only return hostile NPCs.
        limit: Maximum number of results.

    Returns:
        List of NPCs with combat stats.
    """
    try:
        registry = get_npc_registry()
        npcs = registry.search_npcs(
            query=query,
            hostile_only=hostile_only,
            has_stat_block=True,
            limit=limit,
        )

        results = []
        for npc in npcs:
            results.append(NPCSearchResult(
                entity_id=npc.entity_id,
                name=npc.name,
                race=npc.race,
                role=npc.role,
                hp=npc.stat_block.hit_points,
                max_hp=npc.stat_block.max_hit_points,
                ac=npc.stat_block.armor_class,
                initiative_bonus=npc.stat_block.initiative_bonus,
                challenge_rating=npc.stat_block.challenge_rating,
                description=npc.description,
            ))

        return results

    except Exception as e:
        logger.error(f"Failed to search NPCs: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/combat/npcs/{npc_id}")
async def get_npc_for_combat(npc_id: str) -> NPCSearchResult:
    """Get a specific NPC for combat by ID.

    Args:
        npc_id: The NPC entity ID.

    Returns:
        NPC combat info.
    """
    try:
        registry = get_npc_registry()
        npc = registry.get_npc(npc_id)

        if not npc:
            raise HTTPException(status_code=404, detail="NPC not found")

        return NPCSearchResult(
            entity_id=npc.entity_id,
            name=npc.name,
            race=npc.race,
            role=npc.role,
            hp=npc.stat_block.hit_points,
            max_hp=npc.stat_block.max_hit_points,
            ac=npc.stat_block.armor_class,
            initiative_bonus=npc.stat_block.initiative_bonus,
            challenge_rating=npc.stat_block.challenge_rating,
            description=npc.description,
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to get NPC: {e}")
        raise HTTPException(status_code=500, detail=str(e))


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
        # Use exclude_unset=True for npcs so default is_friendly=False doesn't override profile default_faction
        players = [p.model_dump() for p in request.players]
        npcs = [n.model_dump(exclude_unset=True) for n in request.npcs]
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

        # Convert NPC turn results
        npc_results = []
        for npc_turn in result.npc_turn_results:
            npc_results.append(NPCTurnResultItem(
                combatant_name=npc_turn.combatant_name,
                turn_type=npc_turn.turn_type.value,
                round=npc_turn.round,
                narration=npc_turn.narration,
                npc_action=npc_turn.npc_result.model_dump() if npc_turn.npc_result else None,
            ))

        return TurnResultResponse(
            combatant_name=result.combatant_name,
            turn_type=result.turn_type.value,
            round=result.round,
            awaiting_action=result.awaiting_action,
            combat_active=result.combat_active,
            combat_ended_reason=result.combat_ended_reason,
            narration=result.narration,
            npc_action=result.npc_result.model_dump() if result.npc_result else None,
            npc_turn_results=npc_results,
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to end turn: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/combat/turn/advance")
async def advance_turn() -> dict:
    """Advance to the next combatant without processing their turn.

    Use this for step-by-step combat where each turn requires manual confirmation.
    Returns info about the new current combatant.
    """
    try:
        manager = get_combat_manager()
        dm_tools = manager.dm_tools

        if not dm_tools.combat_state:
            raise HTTPException(status_code=400, detail="No active combat")

        # Advance to next turn
        next_turn = dm_tools.next_turn()

        if not next_turn:
            raise HTTPException(status_code=400, detail="Failed to advance turn")

        if next_turn.get("combat_ended"):
            return {
                "combat_active": False,
                "combat_ended_reason": next_turn.get("reason", "Combat ended"),
            }

        # Get current combatant info from combat status
        status = dm_tools.get_combat_status()
        if not status:
            raise HTTPException(status_code=400, detail="No current turn")

        current = status.get("current", {})
        return {
            "combat_active": True,
            "round": dm_tools.combat_state.round,
            "combatant_name": current.get("name", ""),
            "is_npc": current.get("is_npc", False),
            "is_player": current.get("is_player", False),
            "hp": current.get("hp", 0),
            "max_hp": current.get("max_hp", 0),
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to advance turn: {e}")
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


# ===================
# Grid / Position Endpoints
# ===================


class MoveRequest(BaseModel):
    """Request to move a combatant."""

    name: str = Field(..., description="Combatant name")
    x: int = Field(..., description="Target column")
    y: int = Field(..., description="Target row")


class AddMidCombatRequest(BaseModel):
    """Request to add a combatant mid-combat."""

    name: str = Field(..., description="Combatant name")
    initiative_bonus: int = Field(0, description="Initiative modifier")
    hp: int = Field(10, description="Hit points")
    max_hp: Optional[int] = Field(None, description="Max hit points")
    ac: int = Field(12, description="Armor class")
    is_player: bool = Field(False)
    is_npc: bool = Field(False)
    is_friendly: bool = Field(False)
    npc_id: Optional[str] = Field(None)
    x: Optional[int] = Field(None, description="Grid column")
    y: Optional[int] = Field(None, description="Grid row")


class RemoveMidCombatRequest(BaseModel):
    """Request to remove a combatant mid-combat."""

    name: str = Field(..., description="Combatant name")


class GridSizeRequest(BaseModel):
    """Request to set grid dimensions."""

    width: int = Field(20, ge=5, le=50)
    height: int = Field(15, ge=5, le=50)


@router.post("/combat/move")
async def move_combatant(request: MoveRequest) -> dict:
    """Move a combatant to a new grid position."""
    try:
        manager = get_combat_manager()
        result = manager.dm_tools.move_combatant(request.name, request.x, request.y)

        if "error" in result:
            raise HTTPException(status_code=400, detail=result["error"])

        return result

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to move combatant: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/combat/combatant/add")
async def add_combatant_mid_combat(request: AddMidCombatRequest) -> dict:
    """Add a combatant to active combat with initiative roll."""
    try:
        manager = get_combat_manager()
        combatant_dict = request.model_dump()
        if combatant_dict["max_hp"] is None:
            combatant_dict["max_hp"] = combatant_dict["hp"]

        result = manager.dm_tools.add_combatant_mid_combat(combatant_dict)

        if "error" in result:
            raise HTTPException(status_code=400, detail=result["error"])

        return result

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to add combatant: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/combat/combatant/remove")
async def remove_combatant_mid_combat(request: RemoveMidCombatRequest) -> dict:
    """Remove a combatant from active combat."""
    try:
        manager = get_combat_manager()
        result = manager.dm_tools.remove_combatant_mid_combat(request.name)

        if "error" in result:
            raise HTTPException(status_code=400, detail=result["error"])

        return result

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to remove combatant: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/combat/grid")
async def set_grid_size(request: GridSizeRequest) -> dict:
    """Set the combat grid dimensions."""
    try:
        manager = get_combat_manager()
        if not manager.dm_tools.combat_state:
            raise HTTPException(status_code=400, detail="No combat active")

        manager.dm_tools.combat_state.grid_width = request.width
        manager.dm_tools.combat_state.grid_height = request.height

        return {"grid_width": request.width, "grid_height": request.height}

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to set grid size: {e}")
        raise HTTPException(status_code=500, detail=str(e))
