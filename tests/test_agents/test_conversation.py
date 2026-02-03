"""Tests for conversation management."""

import pytest

from backend.agents.conversation import ConversationManager, Message, MessageRole


class TestConversationManager:
    """Test conversation history management."""

    @pytest.fixture
    def manager(self):
        """Create conversation manager."""
        return ConversationManager(max_messages=10, max_tokens=500)

    def test_add_message(self, manager):
        """Test adding a message."""
        msg = manager.add_message(MessageRole.USER, "Hello")
        assert isinstance(msg, Message)
        assert msg.role == MessageRole.USER
        assert msg.content == "Hello"

    def test_add_user_message(self, manager):
        """Test adding user message shortcut."""
        msg = manager.add_user_message("How do saving throws work?")
        assert msg.role == MessageRole.USER
        assert len(manager.messages) == 1

    def test_add_assistant_message(self, manager):
        """Test adding assistant message with metadata."""
        msg = manager.add_assistant_message(
            "Saving throws are...",
            metadata={"sources": ["PHB p.177"]},
        )
        assert msg.role == MessageRole.ASSISTANT
        assert msg.metadata["sources"] == ["PHB p.177"]

    def test_set_system_prompt(self, manager):
        """Test setting system prompt."""
        manager.set_system_prompt("You are a DM assistant.")
        assert manager.system_prompt == "You are a DM assistant."

    def test_get_context_with_system(self, manager):
        """Test getting context includes system prompt."""
        manager.set_system_prompt("System prompt")
        manager.add_user_message("User message")
        manager.add_assistant_message("Assistant message")

        context = manager.get_context(include_system=True)
        assert len(context) == 3
        assert context[0]["role"] == "system"
        assert context[1]["role"] == "user"
        assert context[2]["role"] == "assistant"

    def test_get_context_without_system(self, manager):
        """Test getting context excludes system prompt."""
        manager.set_system_prompt("System prompt")
        manager.add_user_message("User message")

        context = manager.get_context(include_system=False)
        assert len(context) == 1
        assert context[0]["role"] == "user"

    def test_trim_by_message_count(self, manager):
        """Test trimming by message count."""
        for i in range(15):
            manager.add_user_message(f"Message {i}")

        assert len(manager.messages) <= 10

    def test_clear_history(self, manager):
        """Test clearing history."""
        manager.add_user_message("Message 1")
        manager.add_user_message("Message 2")
        manager.clear()
        assert len(manager.messages) == 0

    def test_get_last_n_messages(self, manager):
        """Test getting last N messages."""
        for i in range(5):
            manager.add_user_message(f"Message {i}")

        last_3 = manager.get_last_n_messages(3)
        assert len(last_3) == 3
        assert last_3[0].content == "Message 2"
        assert last_3[2].content == "Message 4"

    def test_search_messages(self, manager):
        """Test searching messages."""
        manager.add_user_message("How does grappling work?")
        manager.add_assistant_message("Grappling requires a contest...")
        manager.add_user_message("What about shoving?")

        results = manager.search_messages("grappling")
        assert len(results) == 2  # Both messages mention grappling

    def test_export_history(self, manager):
        """Test exporting history."""
        manager.add_user_message("Hello")
        manager.add_assistant_message("Hi there!")

        exported = manager.export_history()
        assert len(exported) == 2
        assert "role" in exported[0]
        assert "content" in exported[0]
        assert "timestamp" in exported[0]

    def test_import_history(self, manager):
        """Test importing history."""
        history = [
            {"role": "user", "content": "Imported message 1"},
            {"role": "assistant", "content": "Imported message 2"},
        ]
        manager.import_history(history)

        assert len(manager.messages) == 2
        assert manager.messages[0].content == "Imported message 1"

    def test_get_summary(self, manager):
        """Test getting conversation summary."""
        manager.set_system_prompt("System")
        manager.add_user_message("Hello")
        manager.add_assistant_message("Hi!")

        summary = manager.get_summary()
        assert summary["message_count"] == 2
        assert summary["has_system_prompt"] is True
        assert "estimated_tokens" in summary


class TestMessageModel:
    """Test Message model."""

    def test_message_creation(self):
        """Test creating a message."""
        msg = Message(role=MessageRole.USER, content="Test message")
        assert msg.role == MessageRole.USER
        assert msg.content == "Test message"
        assert msg.timestamp is not None
        assert msg.metadata == {}

    def test_message_with_metadata(self):
        """Test message with metadata."""
        msg = Message(
            role=MessageRole.ASSISTANT,
            content="Response",
            metadata={"sources": ["PHB"]},
        )
        assert msg.metadata["sources"] == ["PHB"]
