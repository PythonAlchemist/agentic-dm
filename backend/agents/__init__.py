"""DM Agent module.

This module provides:
- DM Assistant mode (reactive, helps human DM)
- Autonomous DM mode (proactive, runs the game)
- DM Tools for rules lookup, campaign state, combat, etc.
"""

from backend.agents.tools import DMTools, DiceResult, EncounterResult, NPCResult
from backend.agents.dm_agent import DMAgent, DMMode, DMResponse
from backend.agents.conversation import ConversationManager, Message, MessageRole

__all__ = [
    # Agent
    "DMAgent",
    "DMMode",
    "DMResponse",
    # Tools
    "DMTools",
    "DiceResult",
    "EncounterResult",
    "NPCResult",
    # Conversation
    "ConversationManager",
    "Message",
    "MessageRole",
]
