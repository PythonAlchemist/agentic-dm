"""Context builder for NPC decision-making."""

from typing import Optional

from backend.discord.models import NPCFullProfile
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
