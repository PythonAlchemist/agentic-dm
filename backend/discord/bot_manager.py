"""Discord Bot Manager for NPC bots."""

import asyncio
import logging
from typing import Callable, Optional

from backend.discord.models import NPCFullProfile

logger = logging.getLogger(__name__)

# Discord.py imports - may not be installed yet
try:
    import discord
    from discord.ext import commands

    DISCORD_AVAILABLE = True
except ImportError:
    DISCORD_AVAILABLE = False
    discord = None
    commands = None


class BotInstance:
    """Represents a running Discord bot instance."""

    def __init__(self, npc_id: str):
        self.npc_id = npc_id
        self.bot: Optional[object] = None
        self.ready: bool = False
        self.guild_ids: list[int] = []
        self.npc_profile: Optional[NPCFullProfile] = None


class NPCBotManager:
    """Manages multiple Discord bot instances for NPCs."""

    def __init__(self):
        self._bots: dict[str, BotInstance] = {}
        self._message_handlers: dict[str, Callable] = {}
        self._running = False

        if not DISCORD_AVAILABLE:
            logger.warning(
                "discord.py not installed. Discord bot functionality unavailable. "
                "Install with: pip install discord.py"
            )

    @property
    def is_available(self) -> bool:
        """Check if Discord functionality is available."""
        return DISCORD_AVAILABLE

    async def spawn_bot(self, npc_profile: NPCFullProfile) -> BotInstance:
        """Spawn a new Discord bot for an NPC.

        Args:
            npc_profile: Complete NPC profile with Discord config.

        Returns:
            BotInstance that can be started.
        """
        if not DISCORD_AVAILABLE:
            raise RuntimeError("discord.py not installed")

        config = npc_profile.discord_config
        if not config:
            raise ValueError(f"NPC {npc_profile.name} has no Discord config")

        # Create bot with specific intents
        intents = discord.Intents.default()
        intents.message_content = True
        intents.guilds = True
        intents.members = True

        bot = commands.Bot(
            command_prefix="!",
            intents=intents,
            description=f"NPC Bot: {npc_profile.name}",
        )

        instance = BotInstance(npc_id=npc_profile.entity_id)
        instance.bot = bot
        instance.guild_ids = [int(g) for g in config.discord_guild_ids]
        instance.npc_profile = npc_profile

        # Set up event handlers
        self._setup_bot_events(bot, npc_profile, instance)

        self._bots[npc_profile.entity_id] = instance
        return instance

    def _setup_bot_events(
        self,
        bot: object,
        npc_profile: NPCFullProfile,
        instance: BotInstance,
    ):
        """Configure event handlers for an NPC bot."""

        @bot.event
        async def on_ready():
            logger.info(f"NPC Bot '{npc_profile.name}' connected to Discord")

            # Set presence/status
            if npc_profile.discord_config and npc_profile.discord_config.status_message:
                await bot.change_presence(
                    activity=discord.Game(
                        name=npc_profile.discord_config.status_message
                    )
                )

            instance.ready = True

        @bot.event
        async def on_message(message):
            # Don't respond to own messages
            if message.author == bot.user:
                return

            # Route to message handler if registered
            if npc_profile.entity_id in self._message_handlers:
                try:
                    await self._message_handlers[npc_profile.entity_id](
                        message, npc_profile
                    )
                except Exception as e:
                    logger.error(f"Error in message handler for {npc_profile.name}: {e}")

        @bot.event
        async def on_disconnect():
            logger.warning(f"NPC Bot '{npc_profile.name}' disconnected")
            instance.ready = False

    async def start_bot(self, npc_id: str, token: str):
        """Start a specific NPC bot.

        Args:
            npc_id: The NPC entity ID.
            token: Discord bot token.
        """
        if npc_id not in self._bots:
            raise ValueError(f"Bot {npc_id} not found. Call spawn_bot first.")

        instance = self._bots[npc_id]
        logger.info(f"Starting bot for NPC {npc_id}")

        try:
            await instance.bot.start(token)
        except Exception as e:
            logger.error(f"Failed to start bot {npc_id}: {e}")
            raise

    async def stop_bot(self, npc_id: str):
        """Stop a specific NPC bot.

        Args:
            npc_id: The NPC entity ID.
        """
        if npc_id in self._bots:
            instance = self._bots[npc_id]
            if instance.bot:
                await instance.bot.close()
            instance.ready = False
            logger.info(f"Stopped bot for NPC {npc_id}")

    async def send_message(
        self,
        npc_id: str,
        channel_id: int,
        content: str,
        embed: Optional[object] = None,
    ):
        """Send a message as a specific NPC.

        Args:
            npc_id: The NPC entity ID.
            channel_id: Discord channel ID to send to.
            content: Message content.
            embed: Optional Discord embed.
        """
        if not DISCORD_AVAILABLE:
            raise RuntimeError("discord.py not installed")

        if npc_id not in self._bots or not self._bots[npc_id].ready:
            raise ValueError(f"Bot {npc_id} not ready")

        instance = self._bots[npc_id]
        channel = instance.bot.get_channel(channel_id)

        if channel:
            await channel.send(content=content, embed=embed)
        else:
            logger.warning(f"Channel {channel_id} not found for bot {npc_id}")

    def register_message_handler(
        self,
        npc_id: str,
        handler: Callable,
    ):
        """Register a message handler for an NPC.

        Args:
            npc_id: The NPC entity ID.
            handler: Async function(message, npc_profile) -> None
        """
        self._message_handlers[npc_id] = handler

    def unregister_message_handler(self, npc_id: str):
        """Unregister a message handler.

        Args:
            npc_id: The NPC entity ID.
        """
        if npc_id in self._message_handlers:
            del self._message_handlers[npc_id]

    def get_bot_status(self, npc_id: str) -> dict:
        """Get status of a specific bot.

        Args:
            npc_id: The NPC entity ID.

        Returns:
            Status dictionary.
        """
        if npc_id not in self._bots:
            return {"exists": False, "ready": False}

        instance = self._bots[npc_id]
        return {
            "exists": True,
            "ready": instance.ready,
            "guild_ids": instance.guild_ids,
            "npc_name": instance.npc_profile.name if instance.npc_profile else None,
        }

    def list_bots(self) -> list[dict]:
        """List all registered bots.

        Returns:
            List of bot status dictionaries.
        """
        return [
            {
                "npc_id": npc_id,
                **self.get_bot_status(npc_id),
            }
            for npc_id in self._bots
        ]

    async def run_all(self, npc_tokens: dict[str, str]):
        """Run all registered bots concurrently.

        Args:
            npc_tokens: Mapping of npc_id -> discord token.
        """
        self._running = True
        tasks = []

        for npc_id, token in npc_tokens.items():
            if npc_id in self._bots:
                tasks.append(self.start_bot(npc_id, token))

        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)

    async def stop_all(self):
        """Stop all running bots."""
        self._running = False
        tasks = [self.stop_bot(npc_id) for npc_id in self._bots]
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)


# Global singleton instance
_bot_manager: Optional[NPCBotManager] = None


def get_bot_manager() -> NPCBotManager:
    """Get the global bot manager instance."""
    global _bot_manager
    if _bot_manager is None:
        _bot_manager = NPCBotManager()
    return _bot_manager
