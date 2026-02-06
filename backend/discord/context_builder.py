"""Context builder for NPC decision-making."""

from typing import Optional

from backend.discord.models import NPCFullProfile
from backend.discord.combat_models import CombatMemory, CombatantState
from backend.discord.srd_weapons import grid_distance_ft, get_attack_range
from backend.graph.operations import CampaignGraphOps
from backend.graph.schema import RelationshipType


class NPCContextBuilder:
    """Builds relevant context for NPC decision-making."""

    def __init__(self):
        self.graph_ops = CampaignGraphOps()

    async def build_context(
        self,
        npc: NPCFullProfile,
        user_message: str,
        user_name: str,
    ) -> str:
        """Build context for an NPC response.

        Args:
            npc: The NPC that needs context.
            user_message: What the user said.
            user_name: Who said it.

        Returns:
            Formatted context string.
        """
        context_parts = []

        # 1. Get NPC's relationships
        relationships = self._get_relationships(npc.entity_id)
        if relationships:
            context_parts.append(f"**Your Relationships:**\n{relationships}")

        # 2. Get current location info
        if npc.current_location_id:
            location = self._get_location_context(npc.current_location_id)
            if location:
                context_parts.append(f"**Your Current Location:**\n{location}")

        # 3. Check if user is known to NPC
        user_info = self._get_user_info(npc.entity_id, user_name)
        if user_info:
            context_parts.append(f"**About {user_name}:**\n{user_info}")

        # 4. Get recent interactions
        recent_interactions = self._get_recent_interactions(npc.entity_id)
        if recent_interactions:
            context_parts.append(f"**Recent Interactions:**\n{recent_interactions}")

        return "\n\n".join(context_parts)

    async def build_combat_context(
        self,
        npc: NPCFullProfile,
        combat_state: dict,
        available_targets: list[dict],
    ) -> str:
        """Build context for NPC combat decisions.

        Args:
            npc: The NPC making the decision.
            combat_state: Current combat state.
            available_targets: Valid targets for attacks.

        Returns:
            Formatted combat context string.
        """
        lines = [f"**Combat Round:** {combat_state.get('round', 1)}"]

        # NPC's current status
        stat_block = npc.stat_block
        current_hp = npc.current_hp or stat_block.hit_points
        hp_percent = (current_hp / stat_block.max_hit_points) * 100

        lines.append(f"\n**Your Status:**")
        lines.append(f"- HP: {current_hp}/{stat_block.max_hit_points} ({hp_percent:.0f}%)")
        lines.append(f"- AC: {stat_block.armor_class}")
        if npc.conditions:
            lines.append(f"- Conditions: {', '.join(npc.conditions)}")

        # Available attacks
        lines.append(f"\n**Your Attacks:**")
        for attack in stat_block.attacks:
            lines.append(
                f"- {attack['name']}: +{attack['bonus']} to hit, {attack['damage']} {attack.get('type', '')} damage"
            )

        # Special abilities
        if stat_block.special_abilities:
            lines.append(f"\n**Special Abilities:**")
            for ability in stat_block.special_abilities:
                lines.append(f"- {ability['name']}: {ability['description']}")

        # All combatants
        lines.append(f"\n**All Combatants:**")
        for combatant in combat_state.get("initiative_order", []):
            status = (
                "DOWN"
                if combatant["hp"] <= 0
                else f"{combatant['hp']}/{combatant['max_hp']} HP"
            )
            marker = " (YOU)" if combatant["name"] == npc.name else ""
            player_marker = " [PLAYER]" if combatant.get("is_player") else ""
            lines.append(f"- {combatant['name']}: {status}{marker}{player_marker}")

        # Valid targets
        lines.append(f"\n**Valid Targets:**")
        for target in available_targets:
            # Get relationship if any
            relationship = self._get_relationship_to(npc.entity_id, target.get("name", ""))
            rel_str = f" ({relationship})" if relationship else ""
            lines.append(
                f"- {target['name']}: {target['hp']}/{target['max_hp']} HP{rel_str}"
            )

        # Combat style guidance
        personality = npc.personality
        lines.append(f"\n**Your Combat Style:** {personality.combat_style}")
        lines.append(f"**Aggression Level:** {personality.aggression_level}")
        lines.append(f"**Retreat Threshold:** {personality.retreat_threshold * 100:.0f}% HP")

        if personality.preferred_targets:
            lines.append(f"**Preferred Targets:** {', '.join(personality.preferred_targets)}")

        return "\n".join(lines)

    def build_lean_combat_context(
        self,
        npc: NPCFullProfile,
        combat_state: dict,
        memory: CombatMemory,
        combatants: list[CombatantState],
    ) -> str:
        """Build a lean, situational combat context (~400 tokens).

        Focuses on immediate tactical info without preset dialogue.
        Lets the AI generate authentic responses based on the situation.

        Args:
            npc: The NPC making the decision.
            combat_state: Current combat state.
            memory: Combat memory tracking events and damage.
            combatants: Current state of all combatants.

        Returns:
            Compact prompt string for tactical decisions.
        """
        stat_block = npc.stat_block
        personality = npc.personality
        current_hp = npc.current_hp or stat_block.hit_points

        # Build personality line (concise)
        traits = personality.personality_traits[:2] if personality.personality_traits else []
        trait_str = ", ".join(traits) if traits else personality.combat_style
        lines = [f"You are {npc.name}, a {trait_str} {npc.role}."]

        # Find NPC's own position
        npc_x, npc_y = None, None
        for entry in combat_state.get("initiative_order", []):
            if entry.get("name") == npc.name:
                npc_x = entry.get("x")
                npc_y = entry.get("y")
                break

        # SITUATION block
        lines.append("\nSITUATION:")
        hp_pct = int((current_hp / stat_block.max_hit_points) * 100)
        hp_status = self._hp_status_word(hp_pct)
        lines.append(f"- HP: {current_hp}/{stat_block.max_hit_points} ({hp_status})")
        lines.append(f"- Speed: {stat_block.speed}ft per turn")
        if npc_x is not None and npc_y is not None:
            lines.append(f"- Position: ({npc_x}, {npc_y})")

        if npc.conditions:
            lines.append(f"- Conditions: {', '.join(npc.conditions)}")

        # Spell slots remaining (if caster)
        if stat_block.spell_slots:
            remaining = memory.get_remaining_slots(
                {k: v for k, v in stat_block.spell_slots.items()}
            )
            slot_strs = [f"{lvl}: {cnt}" for lvl, cnt in remaining.items() if cnt > 0]
            if slot_strs:
                lines.append(f"- Slots: {', '.join(slot_strs)}")

        lines.append(f"- Round {combat_state.get('round', 1)}")

        # RECENT EVENTS (from memory)
        events_summary = memory.get_events_summary()
        if events_summary != "Combat just started.":
            lines.append(f"\nRECENT:")
            lines.append(events_summary)

        # Grudge target (who hurt me most)
        grudge = memory.get_grudge_target()
        if grudge:
            dmg = memory.damage_taken_from.get(grudge, 0)
            lines.append(f"\n{grudge} has dealt you {dmg} damage total.")

        # Allies fallen
        if memory.allies_fallen:
            lines.append(f"Fallen allies: {', '.join(memory.allies_fallen)}")

        # Calculate best melee reach from attacks
        best_melee_reach = 5  # default
        for atk in stat_block.attacks:
            cat, normal_range, _ = get_attack_range(atk)
            if cat == "melee" and normal_range > best_melee_reach:
                best_melee_reach = normal_range

        # ENEMIES (only enemies, not allies) with reachability info
        enemies = [c for c in combatants if not c.is_ally and c.hp > 0]
        if enemies:
            lines.append("\nENEMIES:")
            for e in enemies:
                threat = f" [THREAT]" if e.threat_level == "high" else ""
                cond = f" ({', '.join(e.conditions)})" if e.conditions else ""
                dist_ft = e.distance_ft

                # Determine reachability
                if dist_ft is not None:
                    if dist_ft <= best_melee_reach:
                        reach_tag = " [IN MELEE]"
                    elif dist_ft <= stat_block.speed + best_melee_reach:
                        reach_tag = " [REACHABLE]"
                    else:
                        reach_tag = " [FAR]"
                else:
                    reach_tag = ""

                lines.append(f"- {e.name}: {e.hp}/{e.max_hp} HP, AC {e.ac}, {e.distance}{reach_tag}{threat}{cond}")

        # ALLIES (brief)
        allies = [c for c in combatants if c.is_ally and c.hp > 0 and c.name != npc.name]
        if allies:
            lines.append("\nALLIES:")
            for a in allies:
                lines.append(f"- {a.name}: {a.hp}/{a.max_hp} HP")

        # AVAILABLE ACTIONS (compact)
        lines.append("\nAVAILABLE:")

        # Cantrips (at-will)
        if stat_block.cantrips:
            cantrip_strs = []
            for c in stat_block.cantrips[:3]:
                dmg = c.get("damage", "")
                name = c.get("name", "Unknown")
                if dmg:
                    cantrip_strs.append(f"{name} ({dmg})")
                else:
                    cantrip_strs.append(name)
            lines.append(f"- Cantrips: {', '.join(cantrip_strs)}")

        # Spells by level
        if stat_block.spells_known:
            remaining = memory.get_remaining_slots(stat_block.spell_slots)
            for level in ["1st", "2nd", "3rd"]:
                slots_left = remaining.get(level, 0)
                if slots_left > 0:
                    level_spells = [
                        s for s in stat_block.spells_known
                        if s.get("level") == level
                    ]
                    if level_spells:
                        spell_names = [s.get("name", "?") for s in level_spells]
                        lines.append(f"- {level} ({slots_left} slots): {', '.join(spell_names)}")

        # Weapons (with reach/range)
        if stat_block.attacks:
            for atk in stat_block.attacks[:3]:
                category, normal_range, long_range = get_attack_range(atk)
                if category == "melee":
                    range_str = f"reach {normal_range}ft"
                elif long_range and long_range != normal_range:
                    range_str = f"range {normal_range}/{long_range}ft"
                else:
                    range_str = f"range {normal_range}ft"
                lines.append(f"- {atk['name']}: +{atk['bonus']}, {atk['damage']}, {range_str}")

        # Tactical guidance (minimal)
        if hp_pct <= personality.retreat_threshold * 100:
            lines.append(f"\nYou are badly wounded. Consider fleeing or defensive action.")
        elif personality.aggression_level > 0.7:
            lines.append(f"\nYou fight aggressively.")
        elif personality.aggression_level < 0.3:
            lines.append(f"\nYou fight cautiously.")

        lines.append("\nWhat do you do? Include brief dialogue if it fits the moment.")

        return "\n".join(lines)

    def build_combatant_states(
        self,
        npc: NPCFullProfile,
        combat_state: dict,
        memory: CombatMemory,
        npc_is_friendly: bool = False,
    ) -> list[CombatantState]:
        """Convert combat state to CombatantState list for context building.

        Args:
            npc: The NPC perspective.
            combat_state: Current combat state.
            memory: Combat memory for damage tracking.
            npc_is_friendly: True if this NPC fights alongside players.

        Returns:
            List of CombatantState objects.
        """
        combatants = []

        # Find the NPC's own position for distance calculation
        npc_x, npc_y = None, None
        for entry in combat_state.get("initiative_order", []):
            if entry.get("name") == npc.name:
                npc_x = entry.get("x")
                npc_y = entry.get("y")
                break

        for c in combat_state.get("initiative_order", []):
            c_is_player = c.get("is_player", False)
            c_is_friendly_npc = c.get("is_friendly", False)

            # Determine ally status based on this NPC's faction
            if npc_is_friendly:
                # Friendly NPC: players and other friendly NPCs are allies
                is_ally = c_is_player or c_is_friendly_npc
            else:
                # Hostile NPC: other hostile NPCs are allies, players/friendly NPCs are enemies
                is_ally = c.get("is_npc", False) and not c_is_friendly_npc

            # Override with explicit relationships if set
            if c.get("name") in npc.allied_with:
                is_ally = True
            elif c.get("name") in npc.hostile_to:
                is_ally = False

            # Threat assessment
            damage_to_me = memory.damage_taken_from.get(c.get("name", ""), 0)
            hp_pct = c.get("hp", 0) / max(c.get("max_hp", 1), 1)

            if damage_to_me > 10 or hp_pct > 0.8:
                threat = "high"
            elif damage_to_me > 0 or hp_pct > 0.5:
                threat = "medium"
            else:
                threat = "low"

            # Compute actual distance from grid positions
            dist_ft = None
            c_x, c_y = c.get("x"), c.get("y")
            if npc_x is not None and npc_y is not None and c_x is not None and c_y is not None:
                dist_ft = grid_distance_ft(npc_x, npc_y, c_x, c_y)

            distance_str = f"{dist_ft}ft" if dist_ft is not None else "nearby"

            combatants.append(CombatantState(
                name=c.get("name", "Unknown"),
                hp=c.get("hp", 0),
                max_hp=c.get("max_hp", 1),
                ac=c.get("ac", 10),
                is_ally=is_ally,
                distance=distance_str,
                distance_ft=dist_ft,
                conditions=c.get("conditions", []),
                threat_level=threat,
                damage_to_me=damage_to_me,
            ))

        return combatants

    def _hp_status_word(self, hp_pct: int) -> str:
        """Convert HP percentage to a status word."""
        if hp_pct >= 90:
            return "healthy"
        elif hp_pct >= 70:
            return "lightly wounded"
        elif hp_pct >= 50:
            return "wounded"
        elif hp_pct >= 25:
            return "badly wounded"
        else:
            return "critical"

    def _get_relationships(self, npc_id: str) -> str:
        """Get NPC's relationships from the graph."""
        try:
            neighbors = self.graph_ops.get_neighbors(
                entity_id=npc_id,
                max_hops=1,
            )

            lines = []
            for n in neighbors[:10]:
                rel_types = n.get("relationship_types", [])
                for rel_type in rel_types:
                    if rel_type in ["KNOWS", "ALLIED_WITH", "HOSTILE_TO", "MEMBER_OF"]:
                        lines.append(f"- {rel_type.replace('_', ' ').lower()}: {n['name']}")
                        break

            return "\n".join(lines) if lines else ""
        except Exception:
            return ""

    def _get_location_context(self, location_id: str) -> str:
        """Get information about a location."""
        try:
            location = self.graph_ops.get_entity(location_id)
            if not location:
                return ""

            name = location.get("name", "Unknown")
            desc = location.get("description", "")

            result = f"{name}"
            if desc:
                result += f": {desc[:200]}"

            return result
        except Exception:
            return ""

    def _get_user_info(self, npc_id: str, user_name: str) -> str:
        """Check if NPC knows this user/character."""
        try:
            # Search for entity with this name
            results = self.graph_ops.search(
                query=user_name,
                entity_types=["PC", "PLAYER", "NPC"],
                limit=1,
            )

            if not results:
                return ""

            user_entity = results[0]

            # Check for direct relationship
            neighbors = self.graph_ops.get_neighbors(
                entity_id=npc_id,
                max_hops=2,
            )

            for n in neighbors:
                if n["id"] == user_entity["id"]:
                    rel_types = n.get("relationship_types", [])
                    rel = rel_types[0] if rel_types else "acquaintance"
                    desc = user_entity.get("description", "")
                    info = f"You {rel.lower().replace('_', ' ')} {user_name}."
                    if desc:
                        info += f" {desc[:100]}"
                    return info

            return ""
        except Exception:
            return ""

    def _get_relationship_to(self, npc_id: str, target_name: str) -> str:
        """Get NPC's relationship to a specific target."""
        try:
            # Search for target
            results = self.graph_ops.search(
                query=target_name,
                entity_types=["PC", "NPC", "MONSTER"],
                limit=1,
            )

            if not results:
                return ""

            target_id = results[0]["id"]

            # Check relationship
            neighbors = self.graph_ops.get_neighbors(entity_id=npc_id, max_hops=1)

            for n in neighbors:
                if n["id"] == target_id:
                    rel_types = n.get("relationship_types", [])
                    if "HOSTILE_TO" in rel_types:
                        return "hostile"
                    if "ALLIED_WITH" in rel_types:
                        return "ally"
                    if "KNOWS" in rel_types:
                        return "known"

            return ""
        except Exception:
            return ""

    def _get_recent_interactions(self, npc_id: str, limit: int = 3) -> str:
        """Get NPC's recent interactions."""
        try:
            neighbors = self.graph_ops.get_neighbors(
                entity_id=npc_id,
                max_hops=1,
            )

            # Filter for LAST_SPOKE_TO relationships
            interactions = []
            for n in neighbors:
                rel_types = n.get("relationship_types", [])
                if "LAST_SPOKE_TO" in rel_types:
                    interactions.append(n["name"])

            if not interactions:
                return ""

            return "Recently spoke with: " + ", ".join(interactions[:limit])
        except Exception:
            return ""
