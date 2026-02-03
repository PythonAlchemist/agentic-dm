"""Discord integration for AI-controlled NPCs."""

from backend.discord.models import (
    NPCTriggerType,
    VoiceConfig,
    NPCDiscordConfig,
    NPCStatBlock,
    NPCPersonality,
    NPCFullProfile,
)
from backend.discord.combat_models import (
    CombatActionType,
    NPCCombatDecision,
    NPCCombatResult,
)
from backend.discord.npc_registry import NPCRegistry
from backend.discord.bot_manager import NPCBotManager, get_bot_manager
from backend.discord.context_builder import NPCContextBuilder
from backend.discord.npc_agent import NPCAgent, NPCResponse
from backend.discord.message_router import (
    NPCMessageRouter,
    DiscordMessageHandler,
    get_message_handler,
)
from backend.discord.combat_controller import (
    NPCCombatController,
    get_combat_controller,
)

__all__ = [
    # Models
    "NPCTriggerType",
    "VoiceConfig",
    "NPCDiscordConfig",
    "NPCStatBlock",
    "NPCPersonality",
    "NPCFullProfile",
    # Combat models
    "CombatActionType",
    "NPCCombatDecision",
    "NPCCombatResult",
    # Core classes
    "NPCRegistry",
    "NPCBotManager",
    "get_bot_manager",
    "NPCContextBuilder",
    "NPCAgent",
    "NPCResponse",
    "NPCMessageRouter",
    "DiscordMessageHandler",
    "get_message_handler",
    # Combat controller
    "NPCCombatController",
    "get_combat_controller",
]
