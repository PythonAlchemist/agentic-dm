"""Message router for Discord NPC interactions."""

import logging
import re
from typing import Optional

from backend.discord.models import NPCFullProfile, NPCTriggerType
from backend.discord.npc_agent import NPCAgent, NPCResponse
from backend.discord.npc_registry import NPCRegistry

logger = logging.getLogger(__name__)


class ConversationContext:
    """Tracks conversation context for an NPC in a channel."""

    def __init__(self, max_history: int = 10):
        self.max_history = max_history
        self.history: list[dict] = []
        self.last_speaker: Optional[str] = None

    def add_message(self, role: str, content: str, speaker: str) -> None:
        """Add a message to the conversation history.

        Args:
            role: "user" or "assistant".
            content: Message content.
            speaker: Name of the speaker.
        """
        self.history.append({
            "role": role,
            "content": content,
            "speaker": speaker,
        })
        self.last_speaker = speaker

        # Trim to max history
        if len(self.history) > self.max_history:
            self.history = self.history[-self.max_history:]

    def get_history(self) -> list[dict]:
        """Get the conversation history."""
        return self.history.copy()

    def clear(self) -> None:
        """Clear conversation history."""
        self.history.clear()
        self.last_speaker = None


class NPCMessageRouter:
    """Routes Discord messages to appropriate NPC handlers.

    Handles:
    - Direct @mentions of NPC bots
    - Name references in messages
    - DM commands to control NPCs
    """

    def __init__(self):
        """Initialize the message router."""
        self.registry = NPCRegistry()
        self.agent = NPCAgent()

        # Channel -> NPC ID -> ConversationContext
        self._conversations: dict[int, dict[str, ConversationContext]] = {}

        # Authorized DM user IDs
        self._dm_user_ids: set[str] = set()

    def set_dm_users(self, user_ids: list[str]) -> None:
        """Set authorized DM user IDs.

        Args:
            user_ids: List of Discord user IDs.
        """
        self._dm_user_ids = set(user_ids)

    def is_dm_user(self, user_id: str) -> bool:
        """Check if a user is an authorized DM.

        Args:
            user_id: Discord user ID.

        Returns:
            True if user is a DM.
        """
        return str(user_id) in self._dm_user_ids

    def _get_conversation(
        self,
        channel_id: int,
        npc_id: str,
    ) -> ConversationContext:
        """Get or create conversation context.

        Args:
            channel_id: Discord channel ID.
            npc_id: NPC entity ID.

        Returns:
            ConversationContext for this channel/NPC pair.
        """
        if channel_id not in self._conversations:
            self._conversations[channel_id] = {}

        if npc_id not in self._conversations[channel_id]:
            self._conversations[channel_id][npc_id] = ConversationContext()

        return self._conversations[channel_id][npc_id]

    async def check_triggers(
        self,
        message_content: str,
        message_author_id: str,
        message_author_name: str,
        channel_id: int,
        mentioned_user_ids: list[str],
        npc: NPCFullProfile,
    ) -> tuple[bool, Optional[NPCTriggerType]]:
        """Check if a message should trigger an NPC response.

        Args:
            message_content: The message content.
            message_author_id: Discord ID of message author.
            message_author_name: Name of message author.
            channel_id: Discord channel ID.
            mentioned_user_ids: List of mentioned user IDs.
            npc: The NPC to check triggers for.

        Returns:
            Tuple of (should_respond, trigger_type).
        """
        discord_config = npc.discord_config
        if not discord_config:
            return False, None

        # Check if this is a DM command
        if self.is_dm_user(message_author_id):
            if self._is_dm_command(message_content, npc.name):
                return True, NPCTriggerType.DM_COMMAND

        # Check for direct @mention
        if discord_config.discord_application_id in mentioned_user_ids:
            return True, NPCTriggerType.DIRECT_MENTION

        # Check for name reference
        if self._contains_name_reference(message_content, npc.name, npc.aliases):
            return True, NPCTriggerType.NAME_REFERENCE

        return False, None

    def _is_dm_command(self, content: str, npc_name: str) -> bool:
        """Check if message is a DM command for this NPC.

        Args:
            content: Message content.
            npc_name: NPC name.

        Returns:
            True if this is a DM command.
        """
        content_lower = content.lower()

        # Commands like "!npc Grom say Hello" or "/npc Grom..."
        patterns = [
            rf"^!npc\s+{re.escape(npc_name.lower())}\s+",
            rf"^/npc\s+{re.escape(npc_name.lower())}\s+",
            rf"^\[{re.escape(npc_name.lower())}\]\s+",
        ]

        for pattern in patterns:
            if re.match(pattern, content_lower):
                return True

        return False

    def _contains_name_reference(
        self,
        content: str,
        name: str,
        aliases: Optional[list[str]] = None,
    ) -> bool:
        """Check if message contains a reference to the NPC's name.

        Args:
            content: Message content.
            name: NPC's primary name.
            aliases: Optional list of aliases.

        Returns:
            True if name is referenced.
        """
        content_lower = content.lower()

        # Check primary name
        if self._is_word_in_text(name.lower(), content_lower):
            return True

        # Check aliases
        if aliases:
            for alias in aliases:
                if self._is_word_in_text(alias.lower(), content_lower):
                    return True

        return False

    def _is_word_in_text(self, word: str, text: str) -> bool:
        """Check if a word appears as a whole word in text.

        Args:
            word: Word to find.
            text: Text to search.

        Returns:
            True if word is found as whole word.
        """
        # Match word boundaries
        pattern = rf"\b{re.escape(word)}\b"
        return bool(re.search(pattern, text))

    def _extract_dm_command_content(self, content: str, npc_name: str) -> str:
        """Extract the actual command from a DM command message.

        Args:
            content: Full message content.
            npc_name: NPC name.

        Returns:
            The command content after the NPC name.
        """
        content_lower = content.lower()
        name_lower = npc_name.lower()

        # Try different patterns
        patterns = [
            rf"^!npc\s+{re.escape(name_lower)}\s+(.+)",
            rf"^/npc\s+{re.escape(name_lower)}\s+(.+)",
            rf"^\[{re.escape(name_lower)}\]\s+(.+)",
        ]

        for pattern in patterns:
            match = re.match(pattern, content_lower, re.IGNORECASE | re.DOTALL)
            if match:
                # Get the original casing from the original content
                start = match.start(1)
                return content[start:].strip()

        return content

    async def route_message(
        self,
        npc: NPCFullProfile,
        message_content: str,
        message_author_id: str,
        message_author_name: str,
        channel_id: int,
        trigger_type: NPCTriggerType,
    ) -> Optional[NPCResponse]:
        """Route a message to the NPC agent for response.

        Args:
            npc: The NPC to respond as.
            message_content: The message content.
            message_author_id: Discord ID of message author.
            message_author_name: Display name of message author.
            channel_id: Discord channel ID.
            trigger_type: How the NPC was triggered.

        Returns:
            NPCResponse or None if no response generated.
        """
        # Get conversation context
        context = self._get_conversation(channel_id, npc.entity_id)

        # Handle DM commands specially
        if trigger_type == NPCTriggerType.DM_COMMAND:
            command_content = self._extract_dm_command_content(
                message_content, npc.name
            )
            return await self._handle_dm_command(
                npc=npc,
                command=command_content,
                channel_id=channel_id,
                context=context,
            )

        # Generate regular response
        response = await self.agent.generate_response(
            npc=npc,
            user_message=message_content,
            user_name=message_author_name,
            conversation_history=context.get_history(),
        )

        # Update conversation context
        context.add_message("user", message_content, message_author_name)
        context.add_message("assistant", response.message, npc.name)

        return response

    async def _handle_dm_command(
        self,
        npc: NPCFullProfile,
        command: str,
        channel_id: int,
        context: ConversationContext,
    ) -> Optional[NPCResponse]:
        """Handle a DM command for the NPC.

        Args:
            npc: The NPC.
            command: The command content.
            channel_id: Discord channel ID.
            context: Conversation context.

        Returns:
            NPCResponse or None.
        """
        command_lower = command.lower()

        # "say <message>" - NPC says something
        if command_lower.startswith("say "):
            message = command[4:].strip()
            context.add_message("assistant", message, npc.name)
            return NPCResponse(message=message)

        # "emote <action>" - NPC does an action
        if command_lower.startswith("emote "):
            action = command[6:].strip()
            message = f"*{npc.name} {action}*"
            return NPCResponse(message=message, action=action)

        # "react <target> <situation>" - NPC reacts to something
        if command_lower.startswith("react "):
            situation = command[6:].strip()
            response = await self.agent.generate_response(
                npc=npc,
                user_message=f"React to: {situation}",
                user_name="DM",
                conversation_history=context.get_history(),
            )
            context.add_message("assistant", response.message, npc.name)
            return response

        # "clear" - Clear conversation context
        if command_lower == "clear":
            context.clear()
            return NPCResponse(message=f"*{npc.name}'s memory has been cleared.*")

        # Default: treat as something the NPC should say/respond to
        response = await self.agent.generate_response(
            npc=npc,
            user_message=command,
            user_name="DM",
            conversation_history=context.get_history(),
        )
        context.add_message("assistant", response.message, npc.name)
        return response

    def clear_channel_context(self, channel_id: int) -> None:
        """Clear all conversation context for a channel.

        Args:
            channel_id: Discord channel ID.
        """
        if channel_id in self._conversations:
            del self._conversations[channel_id]

    def clear_npc_context(self, npc_id: str) -> None:
        """Clear all conversation context for an NPC.

        Args:
            npc_id: NPC entity ID.
        """
        for channel_conversations in self._conversations.values():
            if npc_id in channel_conversations:
                del channel_conversations[npc_id]


class DiscordMessageHandler:
    """Handler for Discord message events.

    Integrates with the bot manager to process incoming messages.
    """

    def __init__(self):
        """Initialize the message handler."""
        self.router = NPCMessageRouter()
        self.registry = NPCRegistry()

    async def handle_message(
        self,
        message,
        npc: NPCFullProfile,
    ) -> Optional[str]:
        """Handle an incoming Discord message.

        Args:
            message: Discord message object.
            npc: The NPC whose bot received this message.

        Returns:
            Response string or None.
        """
        # Extract message details
        content = message.content
        author_id = str(message.author.id)
        author_name = message.author.display_name
        channel_id = message.channel.id

        # Get mentioned user IDs
        mentioned_ids = [str(m.id) for m in message.mentions]

        # Check triggers
        should_respond, trigger_type = await self.router.check_triggers(
            message_content=content,
            message_author_id=author_id,
            message_author_name=author_name,
            channel_id=channel_id,
            mentioned_user_ids=mentioned_ids,
            npc=npc,
        )

        if not should_respond or trigger_type is None:
            return None

        # Route message and get response
        response = await self.router.route_message(
            npc=npc,
            message_content=content,
            message_author_id=author_id,
            message_author_name=author_name,
            channel_id=channel_id,
            trigger_type=trigger_type,
        )

        if response:
            return response.message

        return None


# Global singleton
_message_handler: Optional[DiscordMessageHandler] = None


def get_message_handler() -> DiscordMessageHandler:
    """Get the global message handler instance."""
    global _message_handler
    if _message_handler is None:
        _message_handler = DiscordMessageHandler()
    return _message_handler
