"""Tests for Discord message router."""

import pytest

from backend.discord.models import (
    NPCTriggerType,
    NPCDiscordConfig,
    NPCStatBlock,
    NPCPersonality,
    NPCFullProfile,
)
from backend.discord.message_router import (
    ConversationContext,
    NPCMessageRouter,
)


class TestConversationContext:
    """Test ConversationContext class."""

    def test_empty_context(self):
        """Test empty conversation context."""
        context = ConversationContext()
        assert len(context.get_history()) == 0
        assert context.last_speaker is None

    def test_add_message(self):
        """Test adding messages to context."""
        context = ConversationContext()
        context.add_message("user", "Hello Grom", "Player1")
        context.add_message("assistant", "Greetings, traveler!", "Grom")

        history = context.get_history()
        assert len(history) == 2
        assert history[0]["role"] == "user"
        assert history[0]["speaker"] == "Player1"
        assert history[1]["role"] == "assistant"
        assert context.last_speaker == "Grom"

    def test_max_history_limit(self):
        """Test that history is trimmed to max length."""
        context = ConversationContext(max_history=3)

        for i in range(5):
            context.add_message("user", f"Message {i}", f"Speaker{i}")

        history = context.get_history()
        assert len(history) == 3
        # Should have the most recent messages
        assert "Message 2" in history[0]["content"]

    def test_clear(self):
        """Test clearing conversation context."""
        context = ConversationContext()
        context.add_message("user", "Hello", "Player1")
        context.add_message("assistant", "Hi", "NPC")

        context.clear()
        assert len(context.get_history()) == 0
        assert context.last_speaker is None


class TestNPCMessageRouter:
    """Test NPCMessageRouter class."""

    @pytest.fixture
    def router(self):
        """Create message router instance."""
        return NPCMessageRouter()

    @pytest.fixture
    def sample_npc(self):
        """Create sample NPC for testing."""
        return NPCFullProfile(
            entity_id="npc_123",
            name="Grom",
            race="orc",
            role="warrior",
            discord_config=NPCDiscordConfig(
                npc_id="npc_123",
                discord_bot_token="fake_token",
                discord_application_id="app_123",
                discord_guild_ids=["guild_1"],
            ),
            stat_block=NPCStatBlock(),
            personality=NPCPersonality(),
            aliases=["Grom the Mighty", "The Orc"],
        )

    def test_dm_user_management(self, router):
        """Test DM user ID management."""
        router.set_dm_users(["user123", "user456"])

        assert router.is_dm_user("user123")
        assert router.is_dm_user("user456")
        assert not router.is_dm_user("user789")

    def test_name_reference_detection(self, router):
        """Test detection of NPC name in message."""
        # Test exact name
        assert router._contains_name_reference("Hey Grom, how are you?", "Grom")
        assert router._contains_name_reference("GROM!", "Grom")
        assert router._contains_name_reference("I spoke to grom yesterday", "Grom")

        # Test word boundaries
        assert not router._contains_name_reference("Telegram is great", "Grom")

    def test_alias_detection(self, router):
        """Test detection of NPC aliases."""
        assert router._contains_name_reference(
            "The Orc approaches",
            "Grom",
            aliases=["Grom the Mighty", "The Orc"],
        )

    def test_dm_command_detection(self, router):
        """Test detection of DM commands."""
        assert router._is_dm_command("!npc Grom say hello", "Grom")
        assert router._is_dm_command("/npc Grom attack", "Grom")
        assert router._is_dm_command("[Grom] I will destroy you!", "Grom")

        # Not a command for this NPC
        assert not router._is_dm_command("!npc Elena say hello", "Grom")

    def test_dm_command_content_extraction(self, router):
        """Test extracting content from DM commands."""
        content = router._extract_dm_command_content(
            "!npc Grom say Hello adventurer!",
            "Grom",
        )
        assert content == "say Hello adventurer!"

        content = router._extract_dm_command_content(
            "[Grom] I challenge you!",
            "Grom",
        )
        assert content == "I challenge you!"

    @pytest.mark.asyncio
    async def test_check_triggers_dm_command(self, router, sample_npc):
        """Test trigger check for DM commands."""
        router.set_dm_users(["dm_user_123"])

        should_respond, trigger = await router.check_triggers(
            message_content="!npc Grom say Hello!",
            message_author_id="dm_user_123",
            message_author_name="DungeonMaster",
            channel_id=12345,
            mentioned_user_ids=[],
            npc=sample_npc,
        )

        assert should_respond is True
        assert trigger == NPCTriggerType.DM_COMMAND

    @pytest.mark.asyncio
    async def test_check_triggers_name_reference(self, router, sample_npc):
        """Test trigger check for name reference."""
        should_respond, trigger = await router.check_triggers(
            message_content="Hey Grom, how's it going?",
            message_author_id="player_123",
            message_author_name="PlayerOne",
            channel_id=12345,
            mentioned_user_ids=[],
            npc=sample_npc,
        )

        assert should_respond is True
        assert trigger == NPCTriggerType.NAME_REFERENCE

    @pytest.mark.asyncio
    async def test_check_triggers_direct_mention(self, router, sample_npc):
        """Test trigger check for direct @mention."""
        should_respond, trigger = await router.check_triggers(
            message_content="@Grom what do you think?",
            message_author_id="player_123",
            message_author_name="PlayerOne",
            channel_id=12345,
            mentioned_user_ids=["app_123"],  # NPC's application ID
            npc=sample_npc,
        )

        assert should_respond is True
        assert trigger == NPCTriggerType.DIRECT_MENTION

    @pytest.mark.asyncio
    async def test_check_triggers_no_trigger(self, router, sample_npc):
        """Test no trigger when NPC not mentioned."""
        should_respond, trigger = await router.check_triggers(
            message_content="Just chatting about the weather",
            message_author_id="player_123",
            message_author_name="PlayerOne",
            channel_id=12345,
            mentioned_user_ids=[],
            npc=sample_npc,
        )

        assert should_respond is False
        assert trigger is None

    def test_conversation_context_per_channel(self, router):
        """Test that conversation context is per-channel."""
        context1 = router._get_conversation(channel_id=100, npc_id="npc_1")
        context2 = router._get_conversation(channel_id=200, npc_id="npc_1")

        context1.add_message("user", "Hello in channel 100", "User1")

        assert len(context1.get_history()) == 1
        assert len(context2.get_history()) == 0

    def test_clear_channel_context(self, router):
        """Test clearing all context for a channel."""
        context = router._get_conversation(channel_id=100, npc_id="npc_1")
        context.add_message("user", "Hello", "User1")

        router.clear_channel_context(100)

        # Should get new empty context
        new_context = router._get_conversation(channel_id=100, npc_id="npc_1")
        assert len(new_context.get_history()) == 0

    def test_clear_npc_context(self, router):
        """Test clearing all context for an NPC."""
        context1 = router._get_conversation(channel_id=100, npc_id="npc_1")
        context2 = router._get_conversation(channel_id=200, npc_id="npc_1")
        context1.add_message("user", "Hello", "User1")
        context2.add_message("user", "Hi", "User2")

        router.clear_npc_context("npc_1")

        new_context1 = router._get_conversation(channel_id=100, npc_id="npc_1")
        new_context2 = router._get_conversation(channel_id=200, npc_id="npc_1")

        assert len(new_context1.get_history()) == 0
        assert len(new_context2.get_history()) == 0
