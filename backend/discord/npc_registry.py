"""NPC Registry for managing NPC configurations and Discord integration."""

import json
from typing import Optional

from backend.discord.models import (
    NPCDiscordConfig,
    NPCFullProfile,
    NPCPersonality,
    NPCStatBlock,
)
from backend.graph.operations import CampaignGraphOps
from backend.graph.schema import EntityType


class NPCRegistry:
    """Registry for NPC configurations with Neo4j integration."""

    def __init__(self):
        self.graph_ops = CampaignGraphOps()
        self._profile_cache: dict[str, NPCFullProfile] = {}

    def get_npc(self, npc_id: str) -> Optional[NPCFullProfile]:
        """Get an NPC profile by ID.

        Args:
            npc_id: The NPC entity ID.

        Returns:
            NPCFullProfile or None if not found.
        """
        # Check cache first
        if npc_id in self._profile_cache:
            return self._profile_cache[npc_id]

        # Fetch from graph
        entity = self.graph_ops.get_entity(npc_id)
        if not entity or entity.get("entity_type") != EntityType.NPC.value:
            return None

        profile = self._entity_to_profile(entity)
        self._profile_cache[npc_id] = profile
        return profile

    def get_npc_with_discord(self, npc_id: str) -> Optional[NPCFullProfile]:
        """Get NPC profile only if Discord is configured.

        Args:
            npc_id: The NPC entity ID.

        Returns:
            NPCFullProfile with discord_config or None.
        """
        profile = self.get_npc(npc_id)
        if profile and profile.discord_config:
            return profile
        return None

    def get_active_npcs(self, guild_id: Optional[str] = None) -> list[NPCFullProfile]:
        """Get all NPCs with active Discord configurations.

        Args:
            guild_id: Optional filter by Discord guild.

        Returns:
            List of NPCFullProfile with active Discord.
        """
        # Query graph for NPCs with discord_active = true
        query = """
        MATCH (n:Entity {entity_type: 'NPC'})
        WHERE n.discord_active = true
        RETURN n
        """
        from backend.core.database import neo4j_session

        results = []
        try:
            with neo4j_session() as session:
                result = session.run(query)
                for record in result:
                    entity = dict(record["n"])
                    profile = self._entity_to_profile(entity)

                    # Filter by guild if specified
                    if guild_id and profile.discord_config:
                        if guild_id not in profile.discord_config.discord_guild_ids:
                            continue

                    if profile.discord_config and profile.discord_config.active:
                        results.append(profile)
        except Exception:
            pass

        return results

    def get_all_discord_npcs(self) -> list[NPCFullProfile]:
        """Get all NPCs that have Discord configured (active or not).

        Returns:
            List of NPCFullProfile with Discord config.
        """
        query = """
        MATCH (n:Entity {entity_type: 'NPC'})
        WHERE n.discord_application_id IS NOT NULL
        RETURN n
        """
        from backend.core.database import neo4j_session

        results = []
        try:
            with neo4j_session() as session:
                result = session.run(query)
                for record in result:
                    entity = dict(record["n"])
                    profile = self._entity_to_profile(entity)
                    if profile.discord_config:
                        results.append(profile)
        except Exception:
            pass

        return results

    def update_discord_config(
        self,
        npc_id: str,
        config: NPCDiscordConfig,
    ) -> bool:
        """Update or create Discord configuration for an NPC.

        Args:
            npc_id: The NPC entity ID.
            config: The Discord configuration.

        Returns:
            True if successful.
        """
        # Store Discord config as properties on the entity
        update_data = {
            "discord_bot_token": config.discord_bot_token,
            "discord_application_id": config.discord_application_id,
            "discord_guild_ids": config.discord_guild_ids,
            "discord_display_name": config.display_name,
            "discord_avatar_url": config.avatar_url,
            "discord_status_message": config.status_message,
            "discord_active": config.active,
        }

        if config.voice_config:
            update_data["discord_voice_config"] = json.dumps(
                config.voice_config.model_dump()
            )

        self.graph_ops.update_entity(npc_id, update_data)

        # Invalidate cache
        if npc_id in self._profile_cache:
            del self._profile_cache[npc_id]

        return True

    def update_stat_block(self, npc_id: str, stats: dict) -> bool:
        """Update NPC combat stats.

        Args:
            npc_id: The NPC entity ID.
            stats: Dictionary of stat updates.

        Returns:
            True if successful.
        """
        # Get existing stat block
        profile = self.get_npc(npc_id)
        if not profile:
            return False

        # Merge with existing
        current_stats = profile.stat_block.model_dump()
        current_stats.update(stats)

        # Store as JSON
        self.graph_ops.update_entity(
            npc_id, {"stat_block": json.dumps(current_stats)}
        )

        # Invalidate cache
        if npc_id in self._profile_cache:
            del self._profile_cache[npc_id]

        return True

    def update_personality(self, npc_id: str, personality: dict) -> bool:
        """Update NPC personality configuration.

        Args:
            npc_id: The NPC entity ID.
            personality: Dictionary of personality updates.

        Returns:
            True if successful.
        """
        # Get existing personality
        profile = self.get_npc(npc_id)
        if not profile:
            return False

        # Merge with existing
        current_personality = profile.personality.model_dump()
        current_personality.update(personality)

        # Store as JSON
        self.graph_ops.update_entity(
            npc_id, {"personality_config": json.dumps(current_personality)}
        )

        # Invalidate cache
        if npc_id in self._profile_cache:
            del self._profile_cache[npc_id]

        return True

    def update_npc_state(
        self,
        npc_id: str,
        current_hp: Optional[int] = None,
        conditions: Optional[list[str]] = None,
        location_id: Optional[str] = None,
    ) -> bool:
        """Update NPC runtime state.

        Args:
            npc_id: The NPC entity ID.
            current_hp: Current hit points.
            conditions: Current conditions.
            location_id: Current location entity ID.

        Returns:
            True if successful.
        """
        update_data = {}

        if current_hp is not None:
            update_data["current_hp"] = current_hp
        if conditions is not None:
            update_data["current_conditions"] = conditions
        if location_id is not None:
            update_data["current_location_id"] = location_id

        if update_data:
            self.graph_ops.update_entity(npc_id, update_data)

            # Invalidate cache
            if npc_id in self._profile_cache:
                del self._profile_cache[npc_id]

        return True

    def _entity_to_profile(self, entity: dict) -> NPCFullProfile:
        """Convert a Neo4j entity to NPCFullProfile.

        Args:
            entity: Entity dictionary from Neo4j.

        Returns:
            NPCFullProfile instance.
        """
        # Parse Discord config if present
        discord_config = None
        if entity.get("discord_application_id"):
            from backend.discord.models import VoiceConfig

            voice_config = None
            if entity.get("discord_voice_config"):
                try:
                    voice_data = json.loads(entity["discord_voice_config"])
                    voice_config = VoiceConfig(**voice_data)
                except (json.JSONDecodeError, TypeError):
                    pass

            discord_config = NPCDiscordConfig(
                npc_id=entity["id"],
                discord_bot_token=entity.get("discord_bot_token", ""),
                discord_application_id=entity["discord_application_id"],
                discord_guild_ids=entity.get("discord_guild_ids", []),
                display_name=entity.get("discord_display_name", entity["name"]),
                avatar_url=entity.get("discord_avatar_url"),
                status_message=entity.get("discord_status_message"),
                active=entity.get("discord_active", False),
                voice_config=voice_config,
            )

        # Parse stat block if present
        stat_block = NPCStatBlock()
        if entity.get("stat_block"):
            try:
                stat_data = json.loads(entity["stat_block"])
                stat_block = NPCStatBlock(**stat_data)
            except (json.JSONDecodeError, TypeError):
                pass

        # Parse personality if present
        personality = NPCPersonality()
        if entity.get("personality_config"):
            try:
                personality_data = json.loads(entity["personality_config"])
                personality = NPCPersonality(**personality_data)
            except (json.JSONDecodeError, TypeError):
                pass

        # Get relationships
        allied_with = []
        hostile_to = []
        try:
            neighbors = self.graph_ops.get_neighbors(entity["id"], max_hops=1)
            for n in neighbors:
                rel_types = n.get("relationship_types", [])
                if "ALLIED_WITH" in rel_types:
                    allied_with.append(n["name"])
                if "HOSTILE_TO" in rel_types:
                    hostile_to.append(n["name"])
        except Exception:
            pass

        return NPCFullProfile(
            entity_id=entity["id"],
            name=entity["name"],
            race=entity.get("race", "human"),
            role=entity.get("role", entity.get("importance", "commoner")),
            description=entity.get("description"),
            discord_config=discord_config,
            stat_block=stat_block,
            personality=personality,
            current_location_id=entity.get("current_location_id"),
            current_hp=entity.get("current_hp"),
            conditions=entity.get("current_conditions", []),
            allied_with=allied_with,
            hostile_to=hostile_to,
            interaction_count=entity.get("interaction_count", 0),
        )

    def create_npc_with_discord(
        self,
        name: str,
        race: str = "human",
        role: str = "commoner",
        description: Optional[str] = None,
        stat_block: Optional[NPCStatBlock] = None,
        personality: Optional[NPCPersonality] = None,
        discord_config: Optional[NPCDiscordConfig] = None,
    ) -> NPCFullProfile:
        """Create a new NPC with full configuration.

        Args:
            name: NPC name.
            race: NPC race.
            role: NPC role/occupation.
            description: NPC description.
            stat_block: Combat stats.
            personality: Personality config.
            discord_config: Discord bot config.

        Returns:
            Created NPCFullProfile.
        """
        # Build properties
        properties = {
            "race": race,
            "role": role,
            "disposition": "neutral",
            "importance": "minor",
        }

        if stat_block:
            properties["stat_block"] = json.dumps(stat_block.model_dump())

        if personality:
            properties["personality_config"] = json.dumps(personality.model_dump())

        # Create entity in graph
        entity = self.graph_ops.create_entity(
            name=name,
            entity_type=EntityType.NPC,
            description=description,
            properties=properties,
        )

        # Add Discord config if provided
        if discord_config and entity:
            discord_config.npc_id = entity["id"]
            self.update_discord_config(entity["id"], discord_config)

        return self.get_npc(entity["id"])
