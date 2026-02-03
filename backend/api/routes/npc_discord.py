"""NPC Discord bot management endpoints."""

import logging
from typing import Optional

from fastapi import APIRouter, HTTPException, BackgroundTasks
from pydantic import BaseModel, Field

from backend.discord import (
    NPCRegistry,
    NPCDiscordConfig,
    NPCStatBlock,
    NPCPersonality,
    NPCFullProfile,
    get_bot_manager,
    get_message_handler,
)

router = APIRouter()
logger = logging.getLogger(__name__)

_registry: Optional[NPCRegistry] = None


def get_registry() -> NPCRegistry:
    """Get or create NPC registry instance."""
    global _registry
    if _registry is None:
        _registry = NPCRegistry()
    return _registry


# ===================
# Request/Response Models
# ===================


class DiscordConfigCreate(BaseModel):
    """Discord configuration creation model."""

    discord_bot_token: str = Field(..., description="Discord bot token")
    discord_application_id: str = Field(..., description="Discord application ID")
    discord_guild_ids: list[str] = Field(
        default_factory=list, description="Guild IDs to join"
    )
    display_name: Optional[str] = Field(None, description="Display name override")
    avatar_url: Optional[str] = Field(None, description="Avatar URL")
    status_message: Optional[str] = Field(None, description="Status/activity message")
    active: bool = Field(True, description="Whether bot should be active")


class DiscordConfigUpdate(BaseModel):
    """Discord configuration update model."""

    discord_guild_ids: Optional[list[str]] = None
    display_name: Optional[str] = None
    avatar_url: Optional[str] = None
    status_message: Optional[str] = None
    active: Optional[bool] = None


class StatBlockUpdate(BaseModel):
    """Stat block update model."""

    armor_class: Optional[int] = None
    hit_points: Optional[int] = None
    max_hit_points: Optional[int] = None
    attacks: Optional[list[dict]] = None
    special_abilities: Optional[list[dict]] = None
    spells: Optional[dict] = None
    challenge_rating: Optional[float] = None


class PersonalityUpdate(BaseModel):
    """Personality update model."""

    personality_traits: Optional[list[str]] = None
    combat_style: Optional[str] = None
    aggression_level: Optional[float] = None
    retreat_threshold: Optional[float] = None
    speech_style: Optional[str] = None
    catchphrases: Optional[list[str]] = None
    secrets: Optional[list[str]] = None
    preferred_targets: Optional[list[str]] = None


class NPCCreate(BaseModel):
    """NPC creation with optional Discord config."""

    name: str
    race: str = "human"
    role: str = "commoner"
    description: Optional[str] = None
    stat_block: Optional[StatBlockUpdate] = None
    personality: Optional[PersonalityUpdate] = None
    discord_config: Optional[DiscordConfigCreate] = None


class BotStatusResponse(BaseModel):
    """Bot status response model."""

    npc_id: str
    npc_name: str
    exists: bool
    ready: bool
    guild_ids: list[int] = Field(default_factory=list)


class SendMessageRequest(BaseModel):
    """Request to send a message as an NPC."""

    channel_id: int
    content: str


class DMUserConfig(BaseModel):
    """DM user configuration."""

    user_ids: list[str]


# ===================
# NPC Discord Configuration
# ===================


@router.post("/npcs/{npc_id}/discord")
async def configure_discord(npc_id: str, config: DiscordConfigCreate) -> dict:
    """Configure Discord bot for an NPC.

    Args:
        npc_id: NPC entity ID.
        config: Discord configuration.

    Returns:
        Success status.
    """
    try:
        registry = get_registry()

        # Verify NPC exists
        npc = registry.get_npc(npc_id)
        if not npc:
            raise HTTPException(status_code=404, detail="NPC not found")

        # Create config object
        discord_config = NPCDiscordConfig(
            npc_id=npc_id,
            discord_bot_token=config.discord_bot_token,
            discord_application_id=config.discord_application_id,
            discord_guild_ids=config.discord_guild_ids,
            display_name=config.display_name or npc.name,
            avatar_url=config.avatar_url,
            status_message=config.status_message,
            active=config.active,
        )

        registry.update_discord_config(npc_id, discord_config)

        return {
            "success": True,
            "npc_id": npc_id,
            "message": "Discord configuration saved",
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to configure Discord for NPC {npc_id}: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.put("/npcs/{npc_id}/discord")
async def update_discord_config(npc_id: str, update: DiscordConfigUpdate) -> dict:
    """Update Discord configuration for an NPC.

    Args:
        npc_id: NPC entity ID.
        update: Configuration updates.

    Returns:
        Updated configuration.
    """
    try:
        registry = get_registry()

        # Get existing config
        npc = registry.get_npc_with_discord(npc_id)
        if not npc:
            raise HTTPException(
                status_code=404,
                detail="NPC not found or has no Discord config",
            )

        # Merge updates
        config = npc.discord_config
        update_data = update.model_dump(exclude_none=True)

        for key, value in update_data.items():
            if hasattr(config, key):
                setattr(config, key, value)

        registry.update_discord_config(npc_id, config)

        return {
            "success": True,
            "npc_id": npc_id,
            "active": config.active,
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to update Discord config for NPC {npc_id}: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.delete("/npcs/{npc_id}/discord")
async def remove_discord_config(npc_id: str) -> dict:
    """Remove Discord configuration from an NPC.

    Args:
        npc_id: NPC entity ID.

    Returns:
        Success status.
    """
    try:
        registry = get_registry()

        # Stop bot if running
        bot_manager = get_bot_manager()
        await bot_manager.stop_bot(npc_id)

        # Remove Discord properties from entity
        from backend.graph.operations import CampaignGraphOps

        ops = CampaignGraphOps()
        ops.update_entity(
            npc_id,
            {
                "discord_bot_token": None,
                "discord_application_id": None,
                "discord_guild_ids": None,
                "discord_active": False,
            },
        )

        return {"success": True, "npc_id": npc_id}
    except Exception as e:
        logger.error(f"Failed to remove Discord config for NPC {npc_id}: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# ===================
# Bot Control
# ===================


@router.post("/npcs/{npc_id}/bot/start")
async def start_bot(npc_id: str, background_tasks: BackgroundTasks) -> dict:
    """Start the Discord bot for an NPC.

    Args:
        npc_id: NPC entity ID.
        background_tasks: FastAPI background tasks.

    Returns:
        Status message.
    """
    try:
        registry = get_registry()
        bot_manager = get_bot_manager()
        message_handler = get_message_handler()

        # Get NPC with Discord config
        npc = registry.get_npc_with_discord(npc_id)
        if not npc:
            raise HTTPException(
                status_code=404,
                detail="NPC not found or has no Discord config",
            )

        if not bot_manager.is_available:
            raise HTTPException(
                status_code=503,
                detail="Discord functionality not available. Install discord.py",
            )

        # Spawn and configure bot
        instance = await bot_manager.spawn_bot(npc)

        # Register message handler
        async def handle_message(message, npc_profile):
            response = await message_handler.handle_message(message, npc_profile)
            if response:
                await message.channel.send(response)

        bot_manager.register_message_handler(npc_id, handle_message)

        # Start bot in background
        background_tasks.add_task(
            bot_manager.start_bot,
            npc_id,
            npc.discord_config.discord_bot_token,
        )

        return {
            "success": True,
            "npc_id": npc_id,
            "npc_name": npc.name,
            "message": "Bot starting",
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to start bot for NPC {npc_id}: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/npcs/{npc_id}/bot/stop")
async def stop_bot(npc_id: str) -> dict:
    """Stop the Discord bot for an NPC.

    Args:
        npc_id: NPC entity ID.

    Returns:
        Status message.
    """
    try:
        bot_manager = get_bot_manager()
        await bot_manager.stop_bot(npc_id)
        bot_manager.unregister_message_handler(npc_id)

        return {
            "success": True,
            "npc_id": npc_id,
            "message": "Bot stopped",
        }
    except Exception as e:
        logger.error(f"Failed to stop bot for NPC {npc_id}: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/npcs/{npc_id}/bot/status", response_model=BotStatusResponse)
async def get_bot_status(npc_id: str) -> BotStatusResponse:
    """Get Discord bot status for an NPC.

    Args:
        npc_id: NPC entity ID.

    Returns:
        Bot status information.
    """
    try:
        registry = get_registry()
        bot_manager = get_bot_manager()

        npc = registry.get_npc(npc_id)
        if not npc:
            raise HTTPException(status_code=404, detail="NPC not found")

        status = bot_manager.get_bot_status(npc_id)

        return BotStatusResponse(
            npc_id=npc_id,
            npc_name=npc.name,
            exists=status.get("exists", False),
            ready=status.get("ready", False),
            guild_ids=status.get("guild_ids", []),
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to get bot status for NPC {npc_id}: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# ===================
# Bot Management
# ===================


@router.get("/npcs/bots")
async def list_active_bots() -> list[dict]:
    """List all active NPC bots.

    Returns:
        List of bot status dictionaries.
    """
    try:
        bot_manager = get_bot_manager()
        return bot_manager.list_bots()
    except Exception as e:
        logger.error(f"Failed to list bots: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/npcs/discord-configured")
async def list_discord_npcs() -> list[dict]:
    """List all NPCs with Discord configuration.

    Returns:
        List of NPC summaries with Discord status.
    """
    try:
        registry = get_registry()
        npcs = registry.get_all_discord_npcs()

        bot_manager = get_bot_manager()

        result = []
        for npc in npcs:
            status = bot_manager.get_bot_status(npc.entity_id)
            result.append({
                "npc_id": npc.entity_id,
                "name": npc.name,
                "race": npc.race,
                "role": npc.role,
                "discord_active": npc.discord_config.active if npc.discord_config else False,
                "bot_ready": status.get("ready", False),
            })

        return result
    except Exception as e:
        logger.error(f"Failed to list Discord NPCs: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# ===================
# NPC Configuration
# ===================


@router.put("/npcs/{npc_id}/stats")
async def update_stats(npc_id: str, stats: StatBlockUpdate) -> dict:
    """Update NPC combat stats.

    Args:
        npc_id: NPC entity ID.
        stats: Stat block updates.

    Returns:
        Updated stat block.
    """
    try:
        registry = get_registry()

        npc = registry.get_npc(npc_id)
        if not npc:
            raise HTTPException(status_code=404, detail="NPC not found")

        update_data = stats.model_dump(exclude_none=True)
        registry.update_stat_block(npc_id, update_data)

        # Get updated NPC
        updated_npc = registry.get_npc(npc_id)

        return {
            "success": True,
            "npc_id": npc_id,
            "stat_block": updated_npc.stat_block.model_dump(),
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to update stats for NPC {npc_id}: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.put("/npcs/{npc_id}/personality")
async def update_personality(npc_id: str, personality: PersonalityUpdate) -> dict:
    """Update NPC personality configuration.

    Args:
        npc_id: NPC entity ID.
        personality: Personality updates.

    Returns:
        Updated personality.
    """
    try:
        registry = get_registry()

        npc = registry.get_npc(npc_id)
        if not npc:
            raise HTTPException(status_code=404, detail="NPC not found")

        update_data = personality.model_dump(exclude_none=True)
        registry.update_personality(npc_id, update_data)

        # Get updated NPC
        updated_npc = registry.get_npc(npc_id)

        return {
            "success": True,
            "npc_id": npc_id,
            "personality": updated_npc.personality.model_dump(),
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to update personality for NPC {npc_id}: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# ===================
# Direct Messaging
# ===================


@router.post("/npcs/{npc_id}/send")
async def send_message_as_npc(npc_id: str, request: SendMessageRequest) -> dict:
    """Send a message as an NPC (DM control).

    Args:
        npc_id: NPC entity ID.
        request: Message to send.

    Returns:
        Success status.
    """
    try:
        bot_manager = get_bot_manager()

        status = bot_manager.get_bot_status(npc_id)
        if not status.get("ready"):
            raise HTTPException(
                status_code=400,
                detail="Bot is not running or not ready",
            )

        await bot_manager.send_message(
            npc_id=npc_id,
            channel_id=request.channel_id,
            content=request.content,
        )

        return {"success": True, "npc_id": npc_id}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to send message as NPC {npc_id}: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# ===================
# DM User Management
# ===================


@router.post("/npcs/dm-users")
async def set_dm_users(config: DMUserConfig) -> dict:
    """Set which Discord users are DMs (can control NPCs).

    Args:
        config: DM user configuration.

    Returns:
        Success status.
    """
    try:
        message_handler = get_message_handler()
        message_handler.router.set_dm_users(config.user_ids)

        return {
            "success": True,
            "dm_user_count": len(config.user_ids),
        }
    except Exception as e:
        logger.error(f"Failed to set DM users: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# ===================
# Full NPC Creation
# ===================


@router.post("/npcs/with-discord")
async def create_npc_with_discord(npc_data: NPCCreate) -> dict:
    """Create a new NPC with optional Discord configuration.

    Args:
        npc_data: NPC creation data.

    Returns:
        Created NPC profile.
    """
    try:
        registry = get_registry()

        # Build stat block
        stat_block = None
        if npc_data.stat_block:
            stat_block = NPCStatBlock(**npc_data.stat_block.model_dump(exclude_none=True))

        # Build personality
        personality = None
        if npc_data.personality:
            personality = NPCPersonality(**npc_data.personality.model_dump(exclude_none=True))

        # Build Discord config
        discord_config = None
        if npc_data.discord_config:
            discord_config = NPCDiscordConfig(
                npc_id="",  # Will be set by registry
                **npc_data.discord_config.model_dump(),
            )

        # Create NPC
        npc = registry.create_npc_with_discord(
            name=npc_data.name,
            race=npc_data.race,
            role=npc_data.role,
            description=npc_data.description,
            stat_block=stat_block,
            personality=personality,
            discord_config=discord_config,
        )

        return {
            "success": True,
            "npc_id": npc.entity_id,
            "name": npc.name,
            "has_discord": npc.discord_config is not None,
        }
    except Exception as e:
        logger.error(f"Failed to create NPC: {e}")
        raise HTTPException(status_code=500, detail=str(e))
