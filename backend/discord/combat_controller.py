"""Combat controller for NPC autonomous combat actions."""

import logging
import re
import random
from typing import Optional

from backend.discord.models import NPCFullProfile
from backend.discord.combat_models import (
    CombatActionType,
    CombatMemory,
    NPCCombatDecision,
    NPCCombatResult,
)
from backend.discord.context_builder import NPCContextBuilder
from backend.discord.npc_agent import NPCAgent
from backend.discord.npc_registry import NPCRegistry
from backend.discord.bot_manager import get_bot_manager, NPCBotManager
from backend.discord.srd_weapons import grid_distance_ft, get_attack_range, parse_spell_range
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
        self.context_builder = NPCContextBuilder()

        # NPC name -> entity ID mapping for active combat
        self._npc_combatant_map: dict[str, str] = {}

        # NPC name -> is_friendly mapping
        self._npc_friendly_map: dict[str, bool] = {}

        # Combat memories per NPC (entity_id -> CombatMemory)
        self._combat_memories: dict[str, CombatMemory] = {}

        # Channel to broadcast combat to
        self._combat_channel_id: Optional[int] = None

    def register_npc_combatant(self, name: str, npc_id: str, is_friendly: bool = False) -> None:
        """Register an NPC in the current combat.

        Args:
            name: The combatant name in initiative order.
            npc_id: The NPC entity ID.
            is_friendly: True if NPC fights alongside players.
        """
        self._npc_combatant_map[name.lower()] = npc_id
        self._npc_friendly_map[name.lower()] = is_friendly
        # Initialize combat memory for this NPC
        if npc_id not in self._combat_memories:
            self._combat_memories[npc_id] = CombatMemory(npc_name=name)

    def is_friendly_npc(self, name: str) -> bool:
        """Check if an NPC is friendly (fights with players).

        Args:
            name: The combatant name.

        Returns:
            True if NPC is friendly.
        """
        return self._npc_friendly_map.get(name.lower(), False)

    def get_combat_memory(self, npc_id: str, npc_name: str = "NPC") -> CombatMemory:
        """Get or create combat memory for an NPC.

        Args:
            npc_id: The NPC entity ID.
            npc_name: The NPC's name (for creating new memory).

        Returns:
            CombatMemory instance for this NPC.
        """
        if npc_id not in self._combat_memories:
            self._combat_memories[npc_id] = CombatMemory(npc_name=npc_name)
        return self._combat_memories[npc_id]

    def record_damage_to_npc(
        self,
        npc_id: str,
        attacker_name: str,
        damage: int,
        weapon: str,
        combat_round: int,
    ) -> None:
        """Record damage dealt to an NPC (called when players attack NPCs).

        Args:
            npc_id: The NPC entity ID.
            attacker_name: Who dealt the damage.
            damage: Amount of damage.
            weapon: What weapon/spell was used.
            combat_round: Current combat round.
        """
        memory = self._combat_memories.get(npc_id)
        if memory:
            memory.record_damage_taken(attacker_name, damage, weapon, combat_round)

    def record_ally_death(self, ally_name: str, killer_name: str, combat_round: int) -> None:
        """Record when an NPC ally falls.

        This notifies all allied NPCs in the combat.

        Args:
            ally_name: The fallen ally's name.
            killer_name: Who killed them.
            combat_round: Current combat round.
        """
        # Notify all NPCs that an ally has fallen
        for npc_id, memory in self._combat_memories.items():
            # Skip the one who died
            if memory.npc_name.lower() != ally_name.lower():
                memory.record_ally_down(ally_name, killer_name, combat_round)

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
        """Get valid targets for an NPC based on faction.

        Friendly NPCs target enemies (hostile NPCs + monsters).
        Hostile NPCs target the party (players + friendly NPCs).

        Args:
            npc_combatant: The NPC's combatant entry.
            combat_state: Current combat state.

        Returns:
            List of valid target dicts.
        """
        targets = []
        npc_name = npc_combatant["name"]
        npc_is_friendly = self.is_friendly_npc(npc_name)

        for combatant in combat_state.initiative_order:
            # Skip self
            if combatant["name"] == npc_name:
                continue

            # Skip dead/fled combatants
            if combatant.get("hp", 0) <= 0 or combatant.get("fled"):
                continue

            # Determine if this combatant is a valid target
            combatant_is_player = combatant.get("is_player", False)
            combatant_is_friendly = combatant.get("is_friendly", False)

            # For friendly NPCs: target enemies (non-player, non-friendly)
            # For hostile NPCs: target party (players + friendly NPCs)
            if npc_is_friendly:
                # Friendly NPC targets enemies
                is_valid_target = not combatant_is_player and not combatant_is_friendly
            else:
                # Hostile NPC targets party (players and friendly NPCs)
                is_valid_target = combatant_is_player or combatant_is_friendly

            if is_valid_target:
                targets.append({
                    "name": combatant["name"],
                    "id": combatant.get("pc_id") or combatant.get("npc_id"),
                    "hp": combatant["hp"],
                    "max_hp": combatant["max_hp"],
                    "ac": combatant.get("ac", 10),
                    "conditions": combatant.get("conditions", []),
                    "is_player": combatant_is_player,
                    "is_friendly": combatant_is_friendly,
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
            logger.info(f"No NPC profile found for {combatant['name']}, using default behavior")
            # Create a default action without full AI
            return await self._process_default_npc_turn(combatant, combat_state)

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

        # Get combat memory for this NPC
        memory = self.get_combat_memory(npc.entity_id, npc.name)
        memory.current_round = combat_state.round

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

            # Build combat state dict
            state_dict = {
                "round": combat_state.round,
                "initiative_order": [
                    {
                        "name": c["name"],
                        "hp": c["hp"],
                        "max_hp": c["max_hp"],
                        "ac": c.get("ac", 10),
                        "is_player": c.get("is_player", False),
                        "is_npc": c.get("is_npc", False),
                        "is_friendly": c.get("is_friendly", False),
                        "conditions": c.get("conditions", []),
                        "side": "player" if c.get("is_player") else "enemy",
                        "x": c.get("x"),
                        "y": c.get("y"),
                    }
                    for c in combat_state.initiative_order
                ],
            }

            # Determine if this NPC is friendly
            npc_is_friendly = self.is_friendly_npc(combatant["name"])

            # Build lean context with memory
            combatant_states = self.context_builder.build_combatant_states(
                npc, state_dict, memory, npc_is_friendly
            )
            lean_context = self.context_builder.build_lean_combat_context(
                npc, state_dict, memory, combatant_states
            )

            # Get combat decision using lean context
            decision = await self.agent.decide_combat_action(
                npc=npc,
                combat_state=state_dict,
                available_targets=targets,
                combat_context=lean_context,
            )

        # Execute the action
        result = await self._execute_action(npc, decision, combatant, combat_state)

        # Record the result in memory
        self._record_action_result(npc.entity_id, result, combat_state.round)

        # Broadcast to Discord if channel is set
        if self._combat_channel_id and npc.discord_config:
            await self._broadcast_result(npc, result)

        return result

    def _record_action_result(
        self,
        npc_id: str,
        result: NPCCombatResult,
        combat_round: int,
    ) -> None:
        """Record the result of an NPC action in memory.

        Args:
            npc_id: The NPC entity ID.
            result: The combat result.
            combat_round: Current round.
        """
        memory = self._combat_memories.get(npc_id)
        if not memory:
            return

        # Record damage dealt
        if result.hit and result.damage_dealt and result.action.target_name:
            weapon = result.action.action_name or "attack"
            memory.record_damage_dealt(
                result.action.target_name,
                result.damage_dealt,
                weapon,
                combat_round,
            )

            # Check if target went down
            if result.target_new_hp is not None and result.target_new_hp <= 0:
                memory.record_enemy_down(result.action.target_name, combat_round)

        # Record miss
        elif result.hit is False and result.action.target_name:
            weapon = result.action.action_name or "attack"
            memory.record_miss(result.action.target_name, weapon, combat_round, is_attacker=True)

        # Record spell usage
        if result.action.action_type == CombatActionType.CAST_SPELL:
            spell_name = result.action.action_name or "unknown spell"
            # Determine spell level (simplified - could be enhanced)
            level = None
            if any(s in spell_name.lower() for s in ["fire bolt", "ray of frost", "shocking grasp"]):
                level = "cantrip"
            elif any(s in spell_name.lower() for s in ["scorching ray", "misty step"]):
                level = "2nd"
            else:
                level = "1st"
            memory.record_spell_used(spell_name, level, combat_round)

    def _find_combatant_by_name(self, name: str, combat_state: CombatState) -> Optional[dict]:
        """Find a combatant by name in the initiative order."""
        for c in combat_state.initiative_order:
            if c["name"].lower() == name.lower():
                return c
        return None

    def _grid_to_notation(self, x: int, y: int) -> str:
        """Convert grid coordinates to chess-like notation (A1, B2, etc.)."""
        col = chr(ord('A') + x) if x < 26 else f"Z{x - 25}"
        row = y + 1
        return f"{col}{row}"

    def _execute_strategic_movement(
        self,
        npc: NPCFullProfile,
        decision: NPCCombatDecision,
        combatant: dict,
        combat_state: CombatState,
        speed_multiplier: float = 1.0,
    ) -> dict:
        """Execute strategic movement toward a target.

        Args:
            npc: The NPC profile.
            decision: The combat decision.
            combatant: The NPC's combatant entry.
            combat_state: Current combat state.
            speed_multiplier: Speed multiplier (2.0 for dash).

        Returns:
            Dict with movement details: {moved_ft, from_pos, to_pos, to_notation, target_name}
        """
        move_target_name = decision.move_toward or decision.target_name
        empty_result = {"moved_ft": 0, "from_pos": None, "to_pos": None, "to_notation": None, "target_name": None}

        if not move_target_name:
            return empty_result

        target = self._find_combatant_by_name(move_target_name, combat_state)
        if not target:
            return empty_result

        # Check if we need to move
        if combatant.get("x") is None or target.get("x") is None:
            return empty_result

        start_dist = grid_distance_ft(
            combatant.get("x", 0), combatant.get("y", 0),
            target.get("x", 0), target.get("y", 0)
        )

        # Already in melee range
        if start_dist <= 5:
            return empty_result

        # Calculate effective speed
        base_speed = npc.stat_block.speed
        effective_speed = int(base_speed * speed_multiplier)

        # Execute movement
        start_x, start_y = combatant.get("x", 0), combatant.get("y", 0)
        new_dist = self._move_toward(combatant, target, effective_speed, combat_state)

        # Calculate distance moved
        end_x, end_y = combatant.get("x", 0), combatant.get("y", 0)
        moved_ft = grid_distance_ft(start_x, start_y, end_x, end_y)

        if moved_ft > 0:
            return {
                "moved_ft": moved_ft,
                "from_pos": (start_x, start_y),
                "to_pos": (end_x, end_y),
                "to_notation": self._grid_to_notation(end_x, end_y),
                "target_name": move_target_name,
            }
        return empty_result

    def _build_stage_directions(
        self,
        npc_name: str,
        movement: dict,
        action_type: str,
        action_name: Optional[str],
        target_name: Optional[str],
        hit: Optional[bool] = None,
        damage: Optional[int] = None,
        bonus_action: Optional[str] = None,
    ) -> str:
        """Build structured stage directions showing action economy.

        Args:
            npc_name: Name of the NPC.
            movement: Movement dict from _execute_strategic_movement.
            action_type: Type of action (attack, cast_spell, dash, etc.)
            action_name: Name of the attack/spell.
            target_name: Target of the action.
            hit: Whether the attack hit.
            damage: Damage dealt.
            bonus_action: Bonus action taken (if any).

        Returns:
            Formatted stage directions string.
        """
        lines = []

        # Movement line
        if movement.get("moved_ft", 0) > 0:
            lines.append(f"**Movement:** Move {movement['moved_ft']}ft to {movement['to_notation']}")

        # Action line
        action_str = ""
        if action_type == "attack":
            weapon = action_name or "weapon"
            if hit is True:
                action_str = f"**Action:** Attack — {weapon} → {target_name} (HIT, {damage} damage)"
            elif hit is False:
                action_str = f"**Action:** Attack — {weapon} → {target_name} (MISS)"
            else:
                action_str = f"**Action:** Attack — {weapon} → {target_name}"
        elif action_type == "cast_spell":
            spell = action_name or "spell"
            if hit is True:
                action_str = f"**Action:** Cast — {spell} → {target_name} (HIT, {damage} damage)"
            elif hit is False:
                action_str = f"**Action:** Cast — {spell} → {target_name} (MISS)"
            elif damage:
                action_str = f"**Action:** Cast — {spell} → {target_name} ({damage} damage)"
            else:
                action_str = f"**Action:** Cast — {spell}" + (f" → {target_name}" if target_name else "")
        elif action_type == "dash":
            action_str = f"**Action:** Dash (double movement)"
        elif action_type == "dodge":
            action_str = f"**Action:** Dodge"
        elif action_type == "disengage":
            action_str = f"**Action:** Disengage"
        elif action_type == "hide":
            action_str = f"**Action:** Hide"
        elif action_type == "flee":
            action_str = f"**Action:** Flee from combat"
        elif action_type == "surrender":
            action_str = f"**Action:** Surrender"
        else:
            action_str = f"**Action:** {action_type.replace('_', ' ').title()}"

        if action_str:
            lines.append(action_str)

        # Bonus action line (if any)
        if bonus_action:
            lines.append(f"**Bonus Action:** {bonus_action}")

        return "\n".join(lines)

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
        movement_info = {"moved_ft": 0}

        # Execute strategic movement first (for non-DASH actions that want to close distance)
        if decision.move_toward and decision.action_type != CombatActionType.DASH:
            movement_info = self._execute_strategic_movement(
                npc, decision, combatant, combat_state
            )

        if decision.action_type == CombatActionType.ATTACK:
            # Execute attack (with range validation + auto-movement)
            attack_roll, damage_roll, hit, damage_dealt, target_new_hp = (
                await self._execute_attack(decision, combat_state, npc=npc, attacker=combatant)
            )

            # Generate narration with stage directions
            if attack_roll is None and hit is None and decision.target_name:
                # Attack couldn't execute (out of range after moving)
                # Get current position for stage directions
                curr_x, curr_y = combatant.get("x", 0), combatant.get("y", 0)
                curr_notation = self._grid_to_notation(curr_x, curr_y)
                stage_dirs = f"**Movement:** Move {movement_info.get('moved_ft', 0)}ft to {curr_notation}\n**Action:** Attack — {decision.action_name or 'weapon'} (OUT OF RANGE)"
                narration = f"{stage_dirs}\n\n_{npc.name} moves toward {decision.target_name} but can't reach them this turn!_"
            else:
                stage_dirs = self._build_stage_directions(
                    npc.name,
                    movement_info,
                    "attack",
                    decision.action_name,
                    decision.target_name,
                    hit=hit,
                    damage=damage_dealt,
                )
                if hit:
                    flavor = self._generate_hit_narration(npc, decision, damage_dealt, target_new_hp)
                else:
                    flavor = self._generate_miss_narration(npc, decision)
                narration = f"{stage_dirs}\n\n_{flavor}_"

        elif decision.action_type == CombatActionType.MULTIATTACK:
            # Handle multiattack (simplified - just do primary attack)
            attack_roll, damage_roll, hit, damage_dealt, target_new_hp = (
                await self._execute_attack(decision, combat_state, npc=npc, attacker=combatant)
            )
            if attack_roll is None and hit is None and decision.target_name:
                curr_x, curr_y = combatant.get("x", 0), combatant.get("y", 0)
                curr_notation = self._grid_to_notation(curr_x, curr_y)
                stage_dirs = f"**Movement:** Move {movement_info.get('moved_ft', 0)}ft to {curr_notation}\n**Action:** Multiattack (OUT OF RANGE)"
                narration = f"{stage_dirs}\n\n_{npc.name} moves toward {decision.target_name} but can't reach them this turn!_"
            else:
                stage_dirs = self._build_stage_directions(
                    npc.name,
                    movement_info,
                    "attack",
                    f"Multiattack — {decision.action_name or 'weapon'}",
                    decision.target_name,
                    hit=hit,
                    damage=damage_dealt,
                )
                if hit:
                    flavor = self._generate_hit_narration(npc, decision, damage_dealt, target_new_hp)
                else:
                    flavor = self._generate_miss_narration(npc, decision)
                narration = f"{stage_dirs}\n\n_{flavor}_"

        elif decision.action_type == CombatActionType.CAST_SPELL:
            # Execute spell attack/damage if applicable
            spell_name = decision.action_name or "a spell"

            if decision.rolls_needed:
                has_attack = any(r["type"] == "attack" for r in decision.rolls_needed)
                has_damage = any(r["type"] == "damage" for r in decision.rolls_needed)

                if has_attack:
                    # Spell attack roll (with range validation)
                    attack_roll, damage_roll, hit, damage_dealt, target_new_hp = (
                        await self._execute_attack(decision, combat_state, npc=npc, attacker=combatant)
                    )
                    if attack_roll is None and hit is None and decision.target_name:
                        stage_dirs = self._build_stage_directions(npc.name, movement_info, "cast_spell", spell_name, decision.target_name)
                        narration = f"{stage_dirs}\n\n_{npc.name} tries to cast {spell_name} at {decision.target_name} but they're out of range!_"
                    else:
                        stage_dirs = self._build_stage_directions(
                            npc.name, movement_info, "cast_spell", spell_name, decision.target_name,
                            hit=hit, damage=damage_dealt
                        )
                        if hit:
                            flavor = self._generate_spell_hit_narration(npc, spell_name, decision.target_name, damage_dealt, target_new_hp)
                        else:
                            flavor = self._generate_spell_miss_narration(npc, spell_name, decision.target_name)
                        narration = f"{stage_dirs}\n\n_{flavor}_"
                elif has_damage:
                    # Auto-hit spell (like Magic Missile) or save-based spell
                    damage_roll = self._roll_damage(decision.rolls_needed)
                    damage_dealt = damage_roll.get("total", 0) if damage_roll else 0
                    if decision.target_name and damage_dealt:
                        target_new_hp = self._apply_damage_to_target(
                            decision.target_name, damage_dealt, combat_state
                        )
                    stage_dirs = self._build_stage_directions(
                        npc.name, movement_info, "cast_spell", spell_name, decision.target_name, damage=damage_dealt
                    )
                    flavor = self._generate_spell_auto_narration(npc, spell_name, decision.target_name, damage_dealt, target_new_hp)
                    narration = f"{stage_dirs}\n\n_{flavor}_"
                else:
                    # Non-damaging spell
                    stage_dirs = self._build_stage_directions(npc.name, movement_info, "cast_spell", spell_name, decision.target_name)
                    narration = f"{stage_dirs}\n\n_{npc.name} casts {spell_name}!_"
            else:
                stage_dirs = self._build_stage_directions(npc.name, movement_info, "cast_spell", spell_name, decision.target_name)
                narration = f"{stage_dirs}\n\n_{npc.name} casts {spell_name}!_"

        elif decision.action_type == CombatActionType.FLEE:
            stage_dirs = self._build_stage_directions(npc.name, movement_info, "flee", None, None)
            narration = f"{stage_dirs}\n\n_{npc.name} attempts to flee from combat!_"
            # Remove from combat
            self._remove_from_combat(combatant, combat_state)

        elif decision.action_type == CombatActionType.SURRENDER:
            stage_dirs = self._build_stage_directions(npc.name, movement_info, "surrender", None, None)
            narration = f"{stage_dirs}\n\n_{npc.name} throws down their weapons and surrenders!_"
            self._remove_from_combat(combatant, combat_state)

        elif decision.action_type == CombatActionType.DODGE:
            stage_dirs = self._build_stage_directions(npc.name, movement_info, "dodge", None, None)
            narration = f"{stage_dirs}\n\n_{npc.name} takes a defensive stance, making themselves harder to hit._"
            conditions_applied.append("dodging")

        elif decision.action_type == CombatActionType.DISENGAGE:
            stage_dirs = self._build_stage_directions(npc.name, movement_info, "disengage", None, None)
            narration = f"{stage_dirs}\n\n_{npc.name} carefully disengages from melee._"

        elif decision.action_type == CombatActionType.DASH:
            # Execute double-speed movement toward target
            dash_movement = self._execute_strategic_movement(
                npc, decision, combatant, combat_state, speed_multiplier=2.0
            )
            moved_ft = dash_movement.get("moved_ft", 0)
            if moved_ft > 0:
                stage_dirs = f"**Movement:** Dash {moved_ft}ft to {dash_movement.get('to_notation', '?')}\n**Action:** Dash (double movement)"
                narration = f"{stage_dirs}\n\n_{npc.name} sprints across the battlefield!_"
            else:
                stage_dirs = "**Action:** Dash"
                narration = f"{stage_dirs}\n\n_{npc.name} takes the Dash action._"

        elif decision.action_type == CombatActionType.HIDE:
            stage_dirs = self._build_stage_directions(npc.name, movement_info, "hide", None, None)
            narration = f"{stage_dirs}\n\n_{npc.name} attempts to hide._"

        elif decision.action_type == CombatActionType.DIALOGUE:
            narration = f'**{npc.name}:** "{decision.combat_dialogue}"' if decision.combat_dialogue else ""

        else:
            stage_dirs = self._build_stage_directions(npc.name, movement_info, decision.action_type.value, decision.action_name, decision.target_name)
            narration = f"{stage_dirs}\n\n_{npc.name} takes an action._"

        # Add combat dialogue if present (prepend it)
        if decision.combat_dialogue and decision.action_type != CombatActionType.DIALOGUE:
            narration = f'*"{decision.combat_dialogue}"*\n\n{narration}'

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
        npc: Optional[NPCFullProfile] = None,
        attacker: Optional[dict] = None,
    ) -> tuple[Optional[dict], Optional[dict], Optional[bool], Optional[int], Optional[int]]:
        """Execute an attack action with range validation and auto-movement.

        Args:
            decision: The combat decision.
            combat_state: Current combat state.
            npc: The NPC profile (for stat lookups and movement speed).
            attacker: The attacker's combatant dict (for position).

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

        # --- Range validation ---
        if attacker and attacker.get("x") is not None and target.get("x") is not None:
            dist_ft = grid_distance_ft(
                attacker.get("x", 0), attacker.get("y", 0),
                target.get("x", 0), target.get("y", 0),
            )

            # Determine attack range from weapon or spell
            attack_dict = None
            if npc and decision.action_name:
                for atk in (npc.stat_block.attacks or []):
                    if atk["name"].lower() == decision.action_name.lower():
                        attack_dict = atk
                        break

            if attack_dict:
                category, normal_range, long_range = get_attack_range(attack_dict)
            elif npc and decision.action_name and decision.action_type == CombatActionType.CAST_SPELL:
                # Look up spell range
                spell_range_str = None
                for s in (npc.stat_block.cantrips or []):
                    if s.get("name", "").lower() == decision.action_name.lower():
                        spell_range_str = s.get("range", "120ft")
                        break
                if not spell_range_str:
                    for s in (npc.stat_block.spells_known or []):
                        if s.get("name", "").lower() == decision.action_name.lower():
                            spell_range_str = s.get("range", "120ft")
                            break
                if spell_range_str:
                    category, normal_range, long_range = parse_spell_range(spell_range_str)
                else:
                    category, normal_range, long_range = ("ranged", 120, 120)
            else:
                # Default: melee, reach 5ft
                category, normal_range, long_range = ("melee", 5, None)

            max_range = long_range if long_range else normal_range

            if dist_ft > normal_range:
                if category == "melee":
                    # Auto-move toward target
                    speed = npc.stat_block.speed if npc else 30
                    new_dist = self._move_toward(attacker, target, speed, combat_state)
                    logger.info(
                        f"{attacker['name']} moves toward {target['name']}: "
                        f"{dist_ft}ft -> {new_dist}ft (reach {normal_range}ft)"
                    )
                    if new_dist > normal_range:
                        # Still out of reach -- spent turn moving
                        logger.info(f"{attacker['name']} cannot reach {target['name']} this turn")
                        return None, None, None, None, None
                elif dist_ft > max_range:
                    # Beyond max range for ranged weapon/spell
                    logger.warning(
                        f"{target['name']} is {dist_ft}ft away, beyond max range {max_range}ft"
                    )
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

    def _generate_spell_hit_narration(
        self,
        npc: NPCFullProfile,
        spell_name: str,
        target: Optional[str],
        damage: Optional[int],
        target_hp: Optional[int],
    ) -> str:
        """Generate narration for a successful spell attack."""
        target_str = target or "the target"
        hit_verbs = ["blasts", "scorches", "strikes", "burns", "freezes", "electrocutes"]
        verb = random.choice(hit_verbs)

        narration = f"{npc.name}'s {spell_name} {verb} {target_str}"
        if damage:
            narration += f" for **{damage} damage**!"
        else:
            narration += "!"

        if target_hp is not None and target_hp <= 0:
            narration += f" **{target_str} goes down!**"

        return narration

    def _generate_spell_miss_narration(
        self,
        npc: NPCFullProfile,
        spell_name: str,
        target: Optional[str],
    ) -> str:
        """Generate narration for a missed spell attack."""
        target_str = target or "the target"
        miss_verbs = ["fizzles past", "streaks past", "misses", "is evaded by"]
        verb = random.choice(miss_verbs)

        return f"{npc.name}'s {spell_name} {verb} {target_str}."

    def _generate_spell_auto_narration(
        self,
        npc: NPCFullProfile,
        spell_name: str,
        target: Optional[str],
        damage: Optional[int],
        target_hp: Optional[int],
    ) -> str:
        """Generate narration for auto-hit spells (Magic Missile, save-based)."""
        target_str = target or "the target"

        if "magic missile" in spell_name.lower():
            narration = f"Three darts of magical force streak from {npc.name}'s fingertips, striking {target_str}"
        elif "burning hands" in spell_name.lower():
            narration = f"A sheet of flames erupts from {npc.name}'s outstretched hands, engulfing {target_str}"
        else:
            narration = f"{npc.name} casts {spell_name} at {target_str}"

        if damage:
            narration += f" for **{damage} damage**!"
        else:
            narration += "!"

        if target_hp is not None and target_hp <= 0:
            narration += f" **{target_str} goes down!**"

        return narration

    def _roll_damage(self, rolls_needed: list[dict]) -> Optional[dict]:
        """Roll damage from roll specifications."""
        for roll in rolls_needed:
            if roll.get("type") == "damage":
                result = self._roll_dice(roll["expression"])
                return {
                    "expression": result["expression"],
                    "rolls": result["rolls"],
                    "total": result["total"],
                }
        return None

    def _apply_damage_to_target(
        self,
        target_name: str,
        damage: int,
        combat_state: CombatState,
    ) -> Optional[int]:
        """Apply damage to a target and return new HP."""
        for c in combat_state.initiative_order:
            if c["name"].lower() == target_name.lower():
                c["hp"] = max(0, c["hp"] - damage)
                return c["hp"]
        return None

    def _remove_from_combat(
        self,
        combatant: dict,
        combat_state: CombatState,
    ) -> None:
        """Remove a combatant from combat (fled/surrendered)."""
        combatant["hp"] = 0  # Marks as "out" without being dead
        combatant["fled"] = True

    def _move_toward(
        self,
        mover: dict,
        target: dict,
        speed_ft: int,
        combat_state: CombatState,
    ) -> int:
        """Move a combatant toward a target, up to their speed.

        Uses simple greedy pathfinding (step in the direction that reduces
        Chebyshev distance). Each square = 5 feet per D&D 5e standard.

        Args:
            mover: The combatant dict (has x, y).
            target: The target combatant dict (has x, y).
            speed_ft: Movement in feet (e.g. 30).
            combat_state: For collision and bounds checking.

        Returns:
            Remaining distance in feet after movement.
        """
        squares = speed_ft // 5
        mx, my = mover.get("x", 0), mover.get("y", 0)
        tx, ty = target.get("x", 0), target.get("y", 0)

        for _ in range(squares):
            # Already adjacent?
            if max(abs(tx - mx), abs(ty - my)) <= 1:
                break

            # Step direction
            dx = 0 if tx == mx else (1 if tx > mx else -1)
            dy = 0 if ty == my else (1 if ty > my else -1)

            new_x, new_y = mx + dx, my + dy

            # Bounds check
            if (new_x < 0 or new_x >= combat_state.grid_width or
                    new_y < 0 or new_y >= combat_state.grid_height):
                break

            # Collision check (skip dead combatants)
            occupied = any(
                c is not mover and c.get("x") == new_x and
                c.get("y") == new_y and c.get("hp", 0) > 0
                for c in combat_state.initiative_order
            )

            if occupied:
                # Try orthogonal alternatives
                moved = False
                for alt_x, alt_y in [(mx + dx, my), (mx, my + dy)]:
                    if (0 <= alt_x < combat_state.grid_width and
                            0 <= alt_y < combat_state.grid_height):
                        alt_occupied = any(
                            c is not mover and c.get("x") == alt_x and
                            c.get("y") == alt_y and c.get("hp", 0) > 0
                            for c in combat_state.initiative_order
                        )
                        if not alt_occupied:
                            new_x, new_y = alt_x, alt_y
                            moved = True
                            break
                if not moved:
                    break  # Stuck

            mx, my = new_x, new_y

        # Update position
        mover["x"] = mx
        mover["y"] = my

        return grid_distance_ft(mx, my, tx, ty)

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

    async def _process_default_npc_turn(
        self,
        combatant: dict,
        combat_state: CombatState,
    ) -> NPCCombatResult:
        """Process a turn for an NPC without a full profile.

        Uses simple default behavior: attack the nearest player.

        Args:
            combatant: The NPC combatant dict.
            combat_state: Current combat state.

        Returns:
            NPCCombatResult with basic attack action.
        """
        npc_name = combatant["name"]

        # Find a valid target (any living player)
        target = None
        for c in combat_state.initiative_order:
            if c.get("is_player") and c.get("hp", 0) > 0:
                target = c
                break

        if not target:
            # No valid targets, skip turn
            return NPCCombatResult(
                npc_id=combatant.get("npc_id", "unknown"),
                npc_name=npc_name,
                action=NPCCombatDecision(
                    npc_id=combatant.get("npc_id", "unknown"),
                    round=combat_state.round,
                    action_type=CombatActionType.DIALOGUE,
                    reasoning="No valid targets",
                    combat_dialogue="There's no one left to fight!",
                ),
                narration=f"{npc_name} looks around but finds no targets.",
            )

        # Generate attack phrases
        attack_phrases = [
            f"You'll regret coming here!",
            f"Die, adventurer!",
            f"For glory!",
            f"I'll crush you!",
            f"Your gold is mine!",
            f"Prepare to meet your end!",
        ]
        dialogue = random.choice(attack_phrases)

        # Create attack decision
        decision = NPCCombatDecision(
            npc_id=combatant.get("npc_id", "unknown"),
            round=combat_state.round,
            action_type=CombatActionType.ATTACK,
            action_name="Attack",
            target_name=target["name"],
            reasoning=f"Attacking {target['name']} as the nearest threat",
            combat_dialogue=dialogue,
            rolls_needed=[
                {"type": "attack", "expression": "1d20+4"},
                {"type": "damage", "expression": "1d6+2"},
            ],
        )

        # Track position before attack (for movement stage directions)
        start_x, start_y = combatant.get("x", 0), combatant.get("y", 0)

        # Execute the attack (with range validation + auto-movement)
        attack_roll, damage_roll, hit, damage_dealt, target_new_hp = (
            await self._execute_attack(decision, combat_state, npc=None, attacker=combatant)
        )

        # Check if movement occurred
        end_x, end_y = combatant.get("x", 0), combatant.get("y", 0)
        moved_ft = grid_distance_ft(start_x, start_y, end_x, end_y)
        end_notation = self._grid_to_notation(end_x, end_y)

        # Generate narration with stage directions
        if attack_roll is None and hit is None and target:
            stage_dirs = f"**Movement:** Move {moved_ft}ft to {end_notation}\n**Action:** Attack — weapon (OUT OF RANGE)"
            narration = (
                f"{stage_dirs}\n\n"
                f"_{npc_name} moves toward {target['name']} but can't reach them this turn!_"
            )
        elif hit:
            movement_line = f"**Movement:** Move {moved_ft}ft to {end_notation}\n" if moved_ft > 0 else ""
            stage_dirs = f"{movement_line}**Action:** Attack — weapon\n**Result:** Hit! {damage_dealt} damage"
            narration = f"{stage_dirs}\n\n_{npc_name} strikes {target['name']}!_"
            if target_new_hp is not None and target_new_hp <= 0:
                narration += f" **{target['name']} goes down!**"
        else:
            movement_line = f"**Movement:** Move {moved_ft}ft to {end_notation}\n" if moved_ft > 0 else ""
            stage_dirs = f"{movement_line}**Action:** Attack — weapon\n**Result:** Miss"
            narration = f"{stage_dirs}\n\n_{npc_name}'s attack misses {target['name']}._"

        return NPCCombatResult(
            npc_id=combatant.get("npc_id", "unknown"),
            npc_name=npc_name,
            action=decision,
            attack_roll=attack_roll,
            damage_roll=damage_roll,
            hit=hit,
            damage_dealt=damage_dealt,
            target_new_hp=target_new_hp,
            narration=narration,
        )

    def clear_combat(self) -> None:
        """Clear NPC combatant registrations and memories."""
        self._npc_combatant_map.clear()
        self._npc_friendly_map.clear()
        self._combat_memories.clear()
        self._combat_channel_id = None


# Global singleton
_combat_controller: Optional[NPCCombatController] = None


def get_combat_controller() -> NPCCombatController:
    """Get the global combat controller instance."""
    global _combat_controller
    if _combat_controller is None:
        _combat_controller = NPCCombatController()
    return _combat_controller
