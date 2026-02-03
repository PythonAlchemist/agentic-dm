"""Conversation history management."""

from datetime import datetime, timezone
from typing import Optional
from enum import Enum

from pydantic import BaseModel, Field


class MessageRole(str, Enum):
    """Message role types."""

    USER = "user"
    ASSISTANT = "assistant"
    SYSTEM = "system"
    TOOL = "tool"


class Message(BaseModel):
    """A single message in the conversation."""

    role: MessageRole
    content: str
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    metadata: dict = Field(default_factory=dict)


class ConversationManager:
    """Manage conversation history with context window limits."""

    def __init__(
        self,
        max_messages: int = 50,
        max_tokens: int = 4000,
        tokens_per_char: float = 0.25,  # Rough estimate
    ):
        """Initialize conversation manager.

        Args:
            max_messages: Maximum messages to keep.
            max_tokens: Approximate token limit for context.
            tokens_per_char: Estimated tokens per character.
        """
        self.max_messages = max_messages
        self.max_tokens = max_tokens
        self.tokens_per_char = tokens_per_char
        self.messages: list[Message] = []
        self.system_prompt: Optional[str] = None

    def set_system_prompt(self, prompt: str) -> None:
        """Set the system prompt.

        Args:
            prompt: System prompt text.
        """
        self.system_prompt = prompt

    def add_message(
        self,
        role: MessageRole,
        content: str,
        metadata: Optional[dict] = None,
    ) -> Message:
        """Add a message to the conversation.

        Args:
            role: Message role.
            content: Message content.
            metadata: Optional metadata.

        Returns:
            The added message.
        """
        message = Message(
            role=role,
            content=content,
            metadata=metadata or {},
        )
        self.messages.append(message)

        # Trim if over limit
        self._trim_history()

        return message

    def add_user_message(self, content: str) -> Message:
        """Add a user message.

        Args:
            content: Message content.

        Returns:
            The added message.
        """
        return self.add_message(MessageRole.USER, content)

    def add_assistant_message(
        self,
        content: str,
        metadata: Optional[dict] = None,
    ) -> Message:
        """Add an assistant message.

        Args:
            content: Message content.
            metadata: Optional metadata (sources, etc.).

        Returns:
            The added message.
        """
        return self.add_message(MessageRole.ASSISTANT, content, metadata)

    def get_context(self, include_system: bool = True) -> list[dict]:
        """Get conversation context for LLM.

        Args:
            include_system: Whether to include system prompt.

        Returns:
            List of message dicts.
        """
        context = []

        if include_system and self.system_prompt:
            context.append({
                "role": "system",
                "content": self.system_prompt,
            })

        for msg in self.messages:
            context.append({
                "role": msg.role.value,
                "content": msg.content,
            })

        return context

    def _trim_history(self) -> None:
        """Trim history to stay within limits."""
        # First, trim by message count
        if len(self.messages) > self.max_messages:
            # Keep the most recent messages, but always keep first 2 for context
            keep_start = 2
            keep_end = self.max_messages - keep_start
            self.messages = self.messages[:keep_start] + self.messages[-keep_end:]

        # Then, trim by approximate token count
        total_chars = sum(len(m.content) for m in self.messages)
        estimated_tokens = int(total_chars * self.tokens_per_char)

        while estimated_tokens > self.max_tokens and len(self.messages) > 4:
            # Remove oldest messages (but keep first 2)
            removed = self.messages.pop(2)
            estimated_tokens -= int(len(removed.content) * self.tokens_per_char)

    def get_summary(self) -> dict:
        """Get conversation summary.

        Returns:
            Summary dict with stats.
        """
        return {
            "message_count": len(self.messages),
            "estimated_tokens": int(
                sum(len(m.content) for m in self.messages) * self.tokens_per_char
            ),
            "has_system_prompt": self.system_prompt is not None,
        }

    def clear(self) -> None:
        """Clear conversation history."""
        self.messages = []

    def get_last_n_messages(self, n: int) -> list[Message]:
        """Get the last N messages.

        Args:
            n: Number of messages.

        Returns:
            List of recent messages.
        """
        return self.messages[-n:]

    def search_messages(self, query: str) -> list[Message]:
        """Search messages containing query.

        Args:
            query: Search query.

        Returns:
            Matching messages.
        """
        query_lower = query.lower()
        return [m for m in self.messages if query_lower in m.content.lower()]

    def export_history(self) -> list[dict]:
        """Export full conversation history.

        Returns:
            List of message dicts.
        """
        return [
            {
                "role": m.role.value,
                "content": m.content,
                "timestamp": m.timestamp.isoformat(),
                "metadata": m.metadata,
            }
            for m in self.messages
        ]

    def import_history(self, messages: list[dict]) -> None:
        """Import conversation history.

        Args:
            messages: List of message dicts.
        """
        self.messages = []
        for m in messages:
            self.messages.append(Message(
                role=MessageRole(m["role"]),
                content=m["content"],
                timestamp=datetime.fromisoformat(m.get("timestamp", datetime.now(timezone.utc).isoformat())),
                metadata=m.get("metadata", {}),
            ))
