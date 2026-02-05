"""Combat Manager for orchestrating player and NPC combat turns."""

import logging
from enum import Enum
from typing import Optional, Callable, Awaitable

from pydantic import BaseModel, Field

from backend.agents.tools import DMTools, CombatState
from backend.discord.models import NPCFullProfile, NPCStatBlock, NPCFaction
from backend.discord.combat_models import NPCCombatResult, CombatActionType
from backend.discord.combat_controller import NPCCombatController
from backend.discord.npc_registry import NPCRegistry

logger = logging.getLogger(__name__)


class TurnType(str, Enum):
    """Type of combatant turn."""

    PLAYER = "player"
    NPC = "npc"
    MONSTER = "monster"  # Non-AI controlled enemy


class TurnResult(BaseModel):
    """Result of processing a turn."""

    combatant_name: str
    turn_type: TurnType
    round: int

    # For NPC turns
    npc_result: Optional[NPCCombatResult] = None

    # For player turns (waiting for input)
    awaiting_action: bool = False
    suggested_actions: list[str] = Field(default_factory=list)

    # Combat state after turn
    combat_active: bool = True
    combat_ended_reason: Optional[str] = None

    # Narration for display
    narration: str = ""

    # Collected NPC turn results (when auto-processing NPC turns)
    npc_turn_results: list["TurnResult"] = Field(default_factory=list)


# Rebuild the model for forward references
TurnResult.model_rebuild()


class CombatConfig(BaseModel):
    """Configuration for combat behavior."""

    # Auto-advance through NPC turns
    auto_npc_turns: bool = True

    # Delay between NPC actions (for dramatic effect, in seconds)
    npc_turn_delay: float = 0.0

    # Whether NPCs announce their turns before acting
    announce_npc_turns: bool = True

    # Auto-end combat when one side is defeated
    auto_end_combat: bool = True


class CombatManager:
    """Manages combat flow between players and AI-controlled NPCs.

    Provides a unified interface for:
    - Starting combat with mixed player/NPC combatants
    - Automatic NPC turn processing
    - Player turn management
    - Combat state tracking and narration
    """

    def __init__(
        self,
        dm_tools: Optional[DMTools] = None,
        combat_controller: Optional[NPCCombatController] = None,
        config: Optional[CombatConfig] = None,
    ):
        """Initialize the combat manager.

        Args:
            dm_tools: DMTools instance for combat operations.
            combat_controller: Controller for NPC combat actions.
            config: Combat configuration.
        """
        self.dm_tools = dm_tools or DMTools()
        self.combat_controller = combat_controller or NPCCombatController(
            dm_tools=self.dm_tools
        )
        self.config = config or CombatConfig()
        self.registry = NPCRegistry()

        # Callbacks for combat events
        self._on_turn_start: Optional[Callable[[dict], Awaitable[None]]] = None
        self._on_turn_end: Optional[Callable[[TurnResult], Awaitable[None]]] = None
        self._on_combat_end: Optional[Callable[[dict], Awaitable[None]]] = None

        # Track NPC entity IDs for combatants
        self._combatant_npc_ids: dict[str, str] = {}

    def set_callbacks(
        self,
        on_turn_start: Optional[Callable[[dict], Awaitable[None]]] = None,
        on_turn_end: Optional[Callable[[TurnResult], Awaitable[None]]] = None,
        on_combat_end: Optional[Callable[[dict], Awaitable[None]]] = None,
    ) -> None:
        """Set event callbacks for combat events.

        Args:
            on_turn_start: Called when a turn begins.
            on_turn_end: Called when a turn ends with result.
            on_combat_end: Called when combat ends.
        """
        self._on_turn_start = on_turn_start
        self._on_turn_end = on_turn_end
        self._on_combat_end = on_combat_end

    async def start_combat(
        self,
        players: list[dict],
        npcs: list[dict],
        monsters: Optional[list[dict]] = None,
    ) -> dict:
        """Start a new combat encounter.

        Args:
            players: List of player combatants with:
                - name: Character name
                - initiative_bonus: Initiative modifier
                - hp, max_hp: Hit points
                - player_id, player_name: Player info
            npcs: List of AI-controlled NPCs with:
                - name: NPC name
                - npc_id: Entity ID for AI control
                - initiative_bonus, hp, max_hp: Stats
            monsters: Optional list of non-AI monsters (DM controlled).

        Returns:
            Combat start info with initiative order.
        """
        # Clear previous combat state
        self._combatant_npc_ids.clear()
        self.combat_controller.clear_combat()

        # Build combatant list
        combatants = []

        # Add players
        for p in players:
            combatants.append({
                "name": p["name"],
                "initiative_bonus": p.get("initiative_bonus", 0),
                "hp": p.get("hp", 20),
                "max_hp": p.get("max_hp", p.get("hp", 20)),
                "ac": p.get("ac", 15),
                "is_player": True,
                "player_id": p.get("player_id"),
                "player_name": p.get("player_name"),
                "pc_id": p.get("pc_id"),
                "character_name": p["name"],
            })

        # Add AI-controlled NPCs
        for npc in npcs:
            npc_id = npc.get("npc_id")
            npc_name = npc["name"]

            # Get NPC profile for stats and default faction
            # Clear cache to ensure fresh profile with default_faction
            profile = None
            if npc_id:
                if npc_id in self.registry._profile_cache:
                    del self.registry._profile_cache[npc_id]
                profile = self.registry.get_npc(npc_id)

            # Determine faction: explicit > profile default > hostile
            if "is_friendly" in npc:
                is_friendly = npc["is_friendly"]
            elif profile and profile.default_faction == NPCFaction.FRIENDLY:
                is_friendly = True
            else:
                is_friendly = False

            # Use profile stats or provided stats
            if profile:
                stats = profile.stat_block
                hp = npc.get("hp") or stats.hit_points or 10
                max_hp = npc.get("max_hp") or stats.max_hit_points or hp
                ac = npc.get("ac") or stats.armor_class or 10
                init_bonus = npc.get("initiative_bonus") if npc.get("initiative_bonus") is not None else (stats.initiative_bonus or 0)
            else:
                hp = npc.get("hp") or 15
                max_hp = npc.get("max_hp") or hp
                ac = npc.get("ac") or 13
                init_bonus = npc.get("initiative_bonus") or 0

            combatants.append({
                "name": npc_name,
                "initiative_bonus": init_bonus,
                "hp": hp,
                "max_hp": max_hp,
                "ac": ac,
                "is_player": False,
                "is_npc": True,
                "npc_id": npc_id,
                "is_friendly": is_friendly,
            })

            # Register with combat controller
            if npc_id:
                self._combatant_npc_ids[npc_name.lower()] = npc_id
                self.combat_controller.register_npc_combatant(npc_name, npc_id, is_friendly)

        # Add non-AI monsters
        if monsters:
            for m in monsters:
                combatants.append({
                    "name": m["name"],
                    "initiative_bonus": m.get("initiative_bonus", 0),
                    "hp": m.get("hp", 10),
                    "max_hp": m.get("max_hp", m.get("hp", 10)),
                    "ac": m.get("ac", 12),
                    "is_player": False,
                    "is_npc": False,
                })

        # Roll initiative and start combat
        combat_state = self.dm_tools.start_combat(combatants)

        current = combat_state.current_combatant()
        npc_turn_results = []

        # If first turn is an NPC and auto_npc_turns is enabled, process it
        if (
            current
            and self.config.auto_npc_turns
            and self._is_npc_combatant(current)
        ):
            result = await self.process_current_turn()
            if result:
                npc_turn_results.append(result)
                # Auto-advance through consecutive NPC turns
                while (
                    result
                    and result.turn_type == TurnType.NPC
                    and result.combat_active
                ):
                    next_result = self.dm_tools.next_turn()
                    if not next_result or next_result.get("combat_ended"):
                        break
                    new_current = self.dm_tools.combat_state.current_combatant()
                    if not new_current or not self._is_npc_combatant(new_current):
                        break
                    result = await self.process_current_turn()
                    if result:
                        npc_turn_results.append(result)

        # Refresh current after potential NPC turns
        current = combat_state.current_combatant()

        # Build response
        initiative_order = []
        for c in combat_state.initiative_order:
            initiative_order.append({
                "name": c["name"],
                "initiative": c["initiative"],
                "hp": c["hp"],
                "max_hp": c["max_hp"],
                "is_player": c.get("is_player", False),
                "is_npc": c.get("is_npc", False),
                "is_friendly": c.get("is_friendly", False),
                "x": c.get("x"),
                "y": c.get("y"),
            })

        response = {
            "combat_started": True,
            "round": combat_state.round,
            "initiative_order": initiative_order,
            "current_turn": current["name"] if current else None,
            "current_is_npc": self._is_npc_combatant(current) if current else False,
            "grid_width": combat_state.grid_width,
            "grid_height": combat_state.grid_height,
        }

        # Include all NPC turn results
        if npc_turn_results:
            response["npc_turn_results"] = [
                {
                    "combatant_name": r.combatant_name,
                    "turn_type": r.turn_type.value,
                    "narration": r.narration,
                    "npc_action": r.npc_result.model_dump() if r.npc_result else None,
                }
                for r in npc_turn_results
            ]

        return response

    def _is_npc_combatant(self, combatant: dict) -> bool:
        """Check if combatant is an AI-controlled NPC."""
        if not combatant:
            return False
        if combatant.get("is_player"):
            return False
        name = combatant.get("name", "").lower()
        return name in self._combatant_npc_ids

    def _get_turn_type(self, combatant: dict) -> TurnType:
        """Determine the turn type for a combatant."""
        if combatant.get("is_player"):
            return TurnType.PLAYER
        if self._is_npc_combatant(combatant):
            return TurnType.NPC
        return TurnType.MONSTER

    async def get_current_turn(self) -> Optional[dict]:
        """Get information about the current turn.

        Returns:
            Current turn info or None if no combat active.
        """
        status = self.dm_tools.get_combat_status()
        if not status:
            return None

        current = status["current"]
        turn_type = self._get_turn_type(current)

        return {
            "combatant": current["name"],
            "turn_type": turn_type.value,
            "is_npc": turn_type == TurnType.NPC,
            "round": status["round"],
            "hp": current["hp"],
            "max_hp": current["max_hp"],
            "conditions": current.get("conditions", []),
        }

    async def process_current_turn(self) -> Optional[TurnResult]:
        """Process the current turn.

        If it's an NPC turn, automatically executes the action.
        If it's a player turn, returns info for the DM.

        Returns:
            TurnResult with action taken or awaiting input.
        """
        status = self.dm_tools.get_combat_status()
        if not status:
            return None

        current = status["current"]
        turn_type = self._get_turn_type(current)

        # Fire turn start callback
        if self._on_turn_start:
            await self._on_turn_start(current)

        if turn_type == TurnType.NPC:
            # AI-controlled NPC - process automatically
            result = await self._process_npc_turn(current, status)
        elif turn_type == TurnType.PLAYER:
            # Player turn - wait for DM input
            result = self._create_player_turn_result(current, status)
        else:
            # Monster (DM controlled) - wait for input
            result = self._create_monster_turn_result(current, status)

        # Fire turn end callback
        if self._on_turn_end:
            await self._on_turn_end(result)

        return result

    async def _process_npc_turn(
        self,
        combatant: dict,
        status: dict,
    ) -> TurnResult:
        """Process an AI-controlled NPC's turn.

        Args:
            combatant: The NPC combatant.
            status: Current combat status.

        Returns:
            TurnResult with NPC action.
        """
        # Announce turn if configured
        narration_parts = []
        if self.config.announce_npc_turns:
            narration_parts.append(f"**{combatant['name']}'s Turn** (Round {status['round']})")

        # Process NPC turn through combat controller
        npc_result = await self.combat_controller.process_npc_turn(
            combatant=combatant,
            combat_state=self.dm_tools.combat_state,
        )

        if npc_result:
            narration_parts.append(npc_result.narration)

            # Check for combat end conditions
            combat_ended, end_reason = self._check_combat_end()

            return TurnResult(
                combatant_name=combatant["name"],
                turn_type=TurnType.NPC,
                round=status["round"],
                npc_result=npc_result,
                awaiting_action=False,
                combat_active=not combat_ended,
                combat_ended_reason=end_reason,
                narration="\n\n".join(narration_parts),
            )
        else:
            # NPC couldn't act (no profile found, etc.)
            narration_parts.append(f"*{combatant['name']} hesitates...*")

            return TurnResult(
                combatant_name=combatant["name"],
                turn_type=TurnType.NPC,
                round=status["round"],
                awaiting_action=False,
                narration="\n\n".join(narration_parts),
            )

    def _create_player_turn_result(
        self,
        combatant: dict,
        status: dict,
    ) -> TurnResult:
        """Create turn result for a player's turn (awaiting input).

        Args:
            combatant: The player combatant.
            status: Current combat status.

        Returns:
            TurnResult awaiting player action.
        """
        # Suggest common actions
        suggestions = [
            "Attack",
            "Cast a spell",
            "Dash",
            "Dodge",
            "Disengage",
            "Help",
            "Hide",
            "Ready an action",
        ]

        player_name = combatant.get("player_name", "Player")
        char_name = combatant.get("character_name", combatant["name"])

        narration = (
            f"**{char_name}'s Turn** (Round {status['round']})\n"
            f"*{player_name}, what does {char_name} do?*\n"
            f"HP: {combatant['hp']}/{combatant['max_hp']}"
        )

        if combatant.get("conditions"):
            narration += f"\nConditions: {', '.join(combatant['conditions'])}"

        return TurnResult(
            combatant_name=combatant["name"],
            turn_type=TurnType.PLAYER,
            round=status["round"],
            awaiting_action=True,
            suggested_actions=suggestions,
            narration=narration,
        )

    def _create_monster_turn_result(
        self,
        combatant: dict,
        status: dict,
    ) -> TurnResult:
        """Create turn result for a DM-controlled monster.

        Args:
            combatant: The monster combatant.
            status: Current combat status.

        Returns:
            TurnResult awaiting DM action.
        """
        narration = (
            f"**{combatant['name']}'s Turn** (Round {status['round']})\n"
            f"*DM: What does {combatant['name']} do?*\n"
            f"HP: {combatant['hp']}/{combatant['max_hp']}"
        )

        return TurnResult(
            combatant_name=combatant["name"],
            turn_type=TurnType.MONSTER,
            round=status["round"],
            awaiting_action=True,
            suggested_actions=["Attack", "Move", "Special ability"],
            narration=narration,
        )

    async def end_turn(self) -> Optional[TurnResult]:
        """End the current turn and advance to the next.

        If the next turn is an NPC and auto_npc_turns is enabled,
        automatically processes that turn too.

        Returns:
            TurnResult for the new current turn, with all NPC results in npc_turn_results.
        """
        # Advance turn
        next_turn = self.dm_tools.next_turn()

        if not next_turn:
            return None

        # Check if combat ended
        if next_turn.get("combat_ended"):
            if self._on_combat_end:
                await self._on_combat_end(next_turn)

            return TurnResult(
                combatant_name="",
                turn_type=TurnType.PLAYER,
                round=self.dm_tools.combat_state.round if self.dm_tools.combat_state else 0,
                combat_active=False,
                combat_ended_reason=next_turn.get("reason", "Combat ended"),
                narration=f"**Combat Ended:** {next_turn.get('reason', 'Unknown')}",
            )

        # Collect all NPC turn results
        npc_results = []

        # Process turns until we hit a player/monster turn or combat ends
        while True:
            # Process current turn
            result = await self.process_current_turn()

            if not result:
                break

            # If it's an NPC turn, save the result and continue
            if result.turn_type == TurnType.NPC and self.config.auto_npc_turns:
                npc_results.append(result)

                if not result.combat_active:
                    # Combat ended
                    result.npc_turn_results = npc_results
                    return result

                # Advance to next turn
                advance = self.dm_tools.next_turn()
                if not advance or advance.get("combat_ended"):
                    result.combat_active = False
                    result.combat_ended_reason = advance.get("reason") if advance else "Combat ended"
                    result.npc_turn_results = npc_results
                    return result
            else:
                # Non-NPC turn - attach collected NPC results and return
                result.npc_turn_results = npc_results
                return result

        return None

    async def process_all_npc_turns(self) -> list[TurnResult]:
        """Process all consecutive NPC turns until a player/monster turn.

        Returns:
            List of TurnResults for all NPC turns processed.
        """
        results = []

        while True:
            turn_info = await self.get_current_turn()
            if not turn_info:
                break

            if not turn_info["is_npc"]:
                break

            result = await self.process_current_turn()
            if result:
                results.append(result)

                if not result.combat_active:
                    break

            # Advance to next turn
            next_turn = self.dm_tools.next_turn()
            if not next_turn or next_turn.get("combat_ended"):
                break

        return results

    def _check_combat_end(self) -> tuple[bool, Optional[str]]:
        """Check if combat should end.

        Returns:
            Tuple of (ended, reason).
        """
        if not self.config.auto_end_combat:
            return False, None

        if not self.dm_tools.combat_state:
            return True, "No combat state"

        party_alive = 0  # Players + friendly NPCs
        enemies_alive = 0  # Hostile NPCs + monsters

        for c in self.dm_tools.combat_state.initiative_order:
            if c["hp"] > 0 and not c.get("fled"):
                if c.get("is_player"):
                    party_alive += 1
                elif c.get("is_friendly"):
                    # Friendly NPC - counts as party
                    party_alive += 1
                else:
                    # Hostile NPC or monster
                    enemies_alive += 1

        if party_alive == 0:
            return True, "Party defeated"
        if enemies_alive == 0:
            return True, "All enemies defeated"

        return False, None

    def apply_damage(self, target: str, damage: int) -> dict:
        """Apply damage to a combatant.

        Args:
            target: Target name.
            damage: Damage amount.

        Returns:
            Damage result.
        """
        result = self.dm_tools.apply_damage(target, damage)

        # Check combat end
        ended, reason = self._check_combat_end()
        if ended:
            result["combat_ended"] = True
            result["end_reason"] = reason

        return result

    def apply_healing(self, target: str, healing: int) -> dict:
        """Apply healing to a combatant.

        Args:
            target: Target name.
            healing: Healing amount.

        Returns:
            Healing result.
        """
        return self.dm_tools.apply_healing(target, healing)

    def add_condition(self, target: str, condition: str) -> dict:
        """Add a condition to a combatant.

        Args:
            target: Target name.
            condition: Condition to add.

        Returns:
            Condition result.
        """
        return self.dm_tools.add_condition(target, condition)

    def remove_condition(self, target: str, condition: str) -> dict:
        """Remove a condition from a combatant.

        Args:
            target: Target name.
            condition: Condition to remove.

        Returns:
            Condition result.
        """
        return self.dm_tools.remove_condition(target, condition)

    def get_combat_status(self) -> Optional[dict]:
        """Get full combat status.

        Returns:
            Combat status or None.
        """
        status = self.dm_tools.get_combat_status()
        if not status:
            return None

        # Enhance with turn type info
        current = status["current"]
        status["current_turn_type"] = self._get_turn_type(current).value
        status["current_is_npc"] = self._is_npc_combatant(current)

        return status

    async def end_combat(self) -> dict:
        """End the current combat.

        Returns:
            Combat summary.
        """
        summary = self.dm_tools.end_combat()

        # Clear registrations
        self._combatant_npc_ids.clear()
        self.combat_controller.clear_combat()

        if self._on_combat_end:
            await self._on_combat_end(summary)

        return summary


# Global singleton
_combat_manager: Optional[CombatManager] = None


def get_combat_manager() -> CombatManager:
    """Get the global combat manager instance."""
    global _combat_manager
    if _combat_manager is None:
        _combat_manager = CombatManager()
    return _combat_manager
