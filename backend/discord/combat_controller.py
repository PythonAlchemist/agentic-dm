"""Combat controller for NPC autonomous combat actions."""

import logging
import re
import random
from typing import Optional

from backend.discord.models import NPCFullProfile
from backend.discord.combat_models import (
    CombatActionType,
    NPCCombatDecision,
    NPCCombatResult,
)
from backend.discord.npc_agent import NPCAgent
from backend.discord.npc_registry import NPCRegistry
from backend.discord.bot_manager import get_bot_manager, NPCBotManager
from backend.agents.tools import DMTools, CombatState

logger = logging.getLogger(__name__)


class NPCCombatController:
    """Controller for NPC combat actions.

    Handles NPC turn detection, decision-making, action execution,
    and result broadcasting via Discord.
    """

    def __init__(
        self,
        dm_tools: Optional[DMTools] = None,
        bot_manager: Optional[NPCBotManager] = None,
    ):
        """Initialize the combat controller.

        Args:
            dm_tools: DMTools instance for combat operations.
            bot_manager: Bot manager for Discord messaging.
        """
        self.dm_tools = dm_tools or DMTools()
        self.bot_manager = bot_manager or get_bot_manager()
        self.registry = NPCRegistry()
        self.agent = NPCAgent()

        # NPC name -> entity ID mapping for active combat
        self._npc_combatant_map: dict[str, str] = {}

        # Channel to broadcast combat to
        self._combat_channel_id: Optional[int] = None

    def register_npc_combatant(self, name: str, npc_id: str) -> None:
        """Register an NPC in the current combat.

        Args:
            name: The combatant name in initiative order.
            npc_id: The NPC entity ID.
        """
        self._npc_combatant_map[name.lower()] = npc_id

    def set_combat_channel(self, channel_id: int) -> None:
        """Set the Discord channel to broadcast combat to.

        Args:
            channel_id: Discord channel ID.
        """
        self._combat_channel_id = channel_id

    def is_npc_turn(self, combatant: dict) -> bool:
        """Check if the current combatant is a registered NPC.

        Args:
            combatant: Combatant dict from initiative order.

        Returns:
            True if this is an NPC's turn.
        """
        if combatant.get("is_player"):
            return False

        name = combatant.get("name", "").lower()
        return name in self._npc_combatant_map

    def get_npc_for_combatant(self, combatant: dict) -> Optional[NPCFullProfile]:
        """Get the NPC profile for a combatant.

        Args:
            combatant: Combatant dict from initiative order.

        Returns:
            NPCFullProfile or None.
        """
        name = combatant.get("name", "").lower()
        npc_id = self._npc_combatant_map.get(name)

        if npc_id:
            return self.registry.get_npc(npc_id)

        return None

    def get_available_targets(
        self,
        npc_combatant: dict,
        combat_state: CombatState,
    ) -> list[dict]:
        """Get valid targets for an NPC.

        Args:
            npc_combatant: The NPC's combatant entry.
            combat_state: Current combat state.

        Returns:
            List of valid target dicts.
        """
        targets = []

        for combatant in combat_state.initiative_order:
            # Skip self
            if combatant["name"] == npc_combatant["name"]:
                continue

            # Skip dead combatants
            if combatant.get("hp", 0) <= 0:
                continue

            # For now, NPCs target players and vice versa
            # More sophisticated ally/enemy detection can be added
            if combatant.get("is_player"):
                targets.append({
                    "name": combatant["name"],
                    "id": combatant.get("pc_id"),
                    "hp": combatant["hp"],
                    "max_hp": combatant["max_hp"],
                    "conditions": combatant.get("conditions", []),
                    "is_player": True,
                })

        return targets

    async def process_npc_turn(
        self,
        combatant: dict,
        combat_state: CombatState,
    ) -> Optional[NPCCombatResult]:
        """Process an NPC's combat turn.

        Args:
            combatant: The NPC combatant dict.
            combat_state: Current combat state.

        Returns:
            NPCCombatResult or None if not an NPC turn.
        """
        # Get NPC profile
        npc = self.get_npc_for_combatant(combatant)
        if not npc:
            logger.warning(f"No NPC profile found for combatant {combatant['name']}")
            return None

        # Update NPC's current HP from combat state
        npc.current_hp = combatant.get("hp", npc.stat_block.hit_points)

        # Check if NPC should retreat
        should_retreat = await self.agent.evaluate_retreat(
            npc=npc,
            current_hp=combatant.get("hp", 10),
            combat_state=combat_state.model_dump() if hasattr(combat_state, 'model_dump') else {
                "round": combat_state.round,
                "initiative_order": combat_state.initiative_order,
            },
        )

        if should_retreat:
            # Generate retreat action
            decision = NPCCombatDecision(
                npc_id=npc.entity_id,
                round=combat_state.round,
                action_type=CombatActionType.FLEE,
                reasoning="HP critically low, retreating",
                combat_dialogue=await self.agent.generate_combat_dialogue(
                    npc, "You are badly wounded and need to escape"
                ),
            )
        else:
            # Get available targets
            targets = self.get_available_targets(combatant, combat_state)

            # Get combat decision from AI
            state_dict = {
                "round": combat_state.round,
                "initiative_order": [
                    {
                        "name": c["name"],
                        "hp": c["hp"],
                        "max_hp": c["max_hp"],
                        "is_player": c.get("is_player", False),
                        "conditions": c.get("conditions", []),
                        "side": "player" if c.get("is_player") else "enemy",
                    }
                    for c in combat_state.initiative_order
                ],
            }

            decision = await self.agent.decide_combat_action(
                npc=npc,
                combat_state=state_dict,
                available_targets=targets,
            )

        # Execute the action
        result = await self._execute_action(npc, decision, combatant, combat_state)

        # Broadcast to Discord if channel is set
        if self._combat_channel_id and npc.discord_config:
            await self._broadcast_result(npc, result)

        return result

    async def _execute_action(
        self,
        npc: NPCFullProfile,
        decision: NPCCombatDecision,
        combatant: dict,
        combat_state: CombatState,
    ) -> NPCCombatResult:
        """Execute the NPC's combat action.

        Args:
            npc: The NPC profile.
            decision: The combat decision.
            combatant: The NPC's combatant entry.
            combat_state: Current combat state.

        Returns:
            NPCCombatResult with outcome.
        """
        attack_roll = None
        damage_roll = None
        hit = None
        damage_dealt = None
        target_new_hp = None
        conditions_applied = []
        narration = ""

        if decision.action_type == CombatActionType.ATTACK:
            # Execute attack
            attack_roll, damage_roll, hit, damage_dealt, target_new_hp = (
                await self._execute_attack(decision, combat_state)
            )

            # Generate narration
            if hit:
                narration = self._generate_hit_narration(
                    npc, decision, damage_dealt, target_new_hp
                )
            else:
                narration = self._generate_miss_narration(npc, decision)

        elif decision.action_type == CombatActionType.MULTIATTACK:
            # Handle multiattack (simplified - just do primary attack)
            attack_roll, damage_roll, hit, damage_dealt, target_new_hp = (
                await self._execute_attack(decision, combat_state)
            )
            narration = f"{npc.name} uses Multiattack!"
            if hit:
                narration += f" {self._generate_hit_narration(npc, decision, damage_dealt, target_new_hp)}"
            else:
                narration += f" {self._generate_miss_narration(npc, decision)}"

        elif decision.action_type == CombatActionType.CAST_SPELL:
            narration = f"{npc.name} casts {decision.action_name or 'a spell'}!"
            if decision.target_name:
                narration += f" targeting {decision.target_name}."

        elif decision.action_type == CombatActionType.FLEE:
            narration = f"{npc.name} attempts to flee from combat!"
            # Remove from combat
            self._remove_from_combat(combatant, combat_state)

        elif decision.action_type == CombatActionType.SURRENDER:
            narration = f"{npc.name} throws down their weapons and surrenders!"
            self._remove_from_combat(combatant, combat_state)

        elif decision.action_type == CombatActionType.DODGE:
            narration = f"{npc.name} takes the Dodge action, making themselves harder to hit."
            conditions_applied.append("dodging")

        elif decision.action_type == CombatActionType.DISENGAGE:
            narration = f"{npc.name} carefully disengages from melee."

        elif decision.action_type == CombatActionType.DASH:
            narration = f"{npc.name} dashes across the battlefield."
            if decision.movement_description:
                narration += f" {decision.movement_description}"

        elif decision.action_type == CombatActionType.HIDE:
            narration = f"{npc.name} attempts to hide."

        elif decision.action_type == CombatActionType.DIALOGUE:
            narration = f'**{npc.name}:** "{decision.combat_dialogue}"' if decision.combat_dialogue else ""

        else:
            narration = f"{npc.name} takes an action."

        # Add combat dialogue if present
        if decision.combat_dialogue and decision.action_type != CombatActionType.DIALOGUE:
            narration = f'*{npc.name}: "{decision.combat_dialogue}"*\n\n{narration}'

        return NPCCombatResult(
            npc_id=npc.entity_id,
            npc_name=npc.name,
            action=decision,
            attack_roll=attack_roll,
            damage_roll=damage_roll,
            hit=hit,
            damage_dealt=damage_dealt,
            target_new_hp=target_new_hp,
            narration=narration,
            conditions_applied=conditions_applied,
        )

    async def _execute_attack(
        self,
        decision: NPCCombatDecision,
        combat_state: CombatState,
    ) -> tuple[Optional[dict], Optional[dict], Optional[bool], Optional[int], Optional[int]]:
        """Execute an attack action.

        Args:
            decision: The combat decision.
            combat_state: Current combat state.

        Returns:
            Tuple of (attack_roll, damage_roll, hit, damage_dealt, target_new_hp).
        """
        if not decision.target_name:
            return None, None, None, None, None

        # Find target
        target = None
        for c in combat_state.initiative_order:
            if c["name"].lower() == decision.target_name.lower():
                target = c
                break

        if not target:
            logger.warning(f"Target {decision.target_name} not found")
            return None, None, None, None, None

        # Roll attack
        attack_roll_result = None
        if decision.rolls_needed:
            for roll in decision.rolls_needed:
                if roll.get("type") == "attack":
                    attack_roll_result = self._roll_dice(roll["expression"])
                    break

        if not attack_roll_result:
            # Default attack roll
            attack_roll_result = self._roll_dice("1d20+5")

        attack_roll = {
            "expression": attack_roll_result["expression"],
            "roll": attack_roll_result["rolls"][0] if attack_roll_result["rolls"] else 0,
            "total": attack_roll_result["total"],
            "critical": attack_roll_result.get("critical", False),
        }

        # Determine hit (assume AC 15 if not specified)
        target_ac = target.get("ac", 15)
        natural_roll = attack_roll_result["rolls"][0] if attack_roll_result["rolls"] else 0
        hit = natural_roll == 20 or (natural_roll != 1 and attack_roll_result["total"] >= target_ac)

        damage_roll = None
        damage_dealt = None
        target_new_hp = None

        if hit:
            # Roll damage
            damage_roll_result = None
            if decision.rolls_needed:
                for roll in decision.rolls_needed:
                    if roll.get("type") == "damage":
                        damage_roll_result = self._roll_dice(roll["expression"])
                        break

            if not damage_roll_result:
                # Default damage
                damage_roll_result = self._roll_dice("1d8+3")

            damage_roll = {
                "expression": damage_roll_result["expression"],
                "rolls": damage_roll_result["rolls"],
                "total": damage_roll_result["total"],
            }

            damage_dealt = damage_roll_result["total"]

            # Double damage on critical
            if natural_roll == 20:
                damage_dealt *= 2

            # Apply damage
            result = self.dm_tools.apply_damage(target["name"], damage_dealt)
            target_new_hp = result.get("current_hp")

        return attack_roll, damage_roll, hit, damage_dealt, target_new_hp

    def _roll_dice(self, expression: str) -> dict:
        """Roll dice and return result dict.

        Args:
            expression: Dice expression like "1d20+5".

        Returns:
            Dict with rolls, total, and critical.
        """
        result = self.dm_tools.roll_dice(expression)
        return {
            "expression": result.expression,
            "rolls": result.rolls,
            "modifier": result.modifier,
            "total": result.total,
            "critical": result.critical,
        }

    def _generate_hit_narration(
        self,
        npc: NPCFullProfile,
        decision: NPCCombatDecision,
        damage: int,
        target_hp: Optional[int],
    ) -> str:
        """Generate narration for a successful hit."""
        attack_name = decision.action_name or "attack"
        target = decision.target_name or "the target"

        hit_verbs = ["strikes", "hits", "slashes", "smashes", "connects with"]
        verb = random.choice(hit_verbs)

        narration = f"{npc.name} {verb} {target} with {attack_name} for **{damage} damage**!"

        if target_hp is not None and target_hp <= 0:
            narration += f" **{target} goes down!**"

        return narration

    def _generate_miss_narration(
        self,
        npc: NPCFullProfile,
        decision: NPCCombatDecision,
    ) -> str:
        """Generate narration for a miss."""
        attack_name = decision.action_name or "attack"
        target = decision.target_name or "the target"

        miss_verbs = ["misses", "swings wide", "fails to connect", "is dodged by"]
        verb = random.choice(miss_verbs)

        return f"{npc.name}'s {attack_name} {verb} {target}."

    def _remove_from_combat(
        self,
        combatant: dict,
        combat_state: CombatState,
    ) -> None:
        """Remove a combatant from combat (fled/surrendered)."""
        combatant["hp"] = 0  # Marks as "out" without being dead
        combatant["fled"] = True

    async def _broadcast_result(
        self,
        npc: NPCFullProfile,
        result: NPCCombatResult,
    ) -> None:
        """Broadcast combat result via Discord.

        Args:
            npc: The NPC profile.
            result: Combat result to broadcast.
        """
        if not self._combat_channel_id or not npc.discord_config:
            return

        try:
            await self.bot_manager.send_message(
                npc_id=npc.entity_id,
                channel_id=self._combat_channel_id,
                content=result.narration,
            )
        except Exception as e:
            logger.error(f"Failed to broadcast combat result: {e}")

    async def handle_next_turn(self) -> Optional[NPCCombatResult]:
        """Advance combat and handle if it's an NPC turn.

        Returns:
            NPCCombatResult if an NPC took their turn, None otherwise.
        """
        if not self.dm_tools.combat_state or not self.dm_tools.combat_state.active:
            return None

        # Get current combatant
        current = self.dm_tools.combat_state.current_combatant()
        if not current:
            return None

        # Check if it's an NPC turn
        if self.is_npc_turn(current):
            return await self.process_npc_turn(
                current,
                self.dm_tools.combat_state,
            )

        return None

    def clear_combat(self) -> None:
        """Clear NPC combatant registrations."""
        self._npc_combatant_map.clear()
        self._combat_channel_id = None


# Global singleton
_combat_controller: Optional[NPCCombatController] = None


def get_combat_controller() -> NPCCombatController:
    """Get the global combat controller instance."""
    global _combat_controller
    if _combat_controller is None:
        _combat_controller = NPCCombatController()
    return _combat_controller
