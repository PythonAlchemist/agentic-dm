"""DM Agent module.

This module provides:
- Unified DM agent for assisting and running games
- DM Tools for rules lookup, campaign state, combat, etc.
"""

from backend.agents.conversation import ConversationManager, Message, MessageRole
from backend.agents.dm_agent import DMAgent, DMResponse
from backend.agents.tools import DiceResult, DMTools, EncounterResult, NPCResult

__all__ = [
    # Agent
    "DMAgent",
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
