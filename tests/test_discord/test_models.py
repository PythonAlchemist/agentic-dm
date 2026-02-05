"""Tests for Discord NPC models."""

import pytest

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


class TestNPCStatBlock:
    """Test NPCStatBlock model."""

    def test_default_values(self):
        """Test default stat block values."""
        stats = NPCStatBlock()
        assert stats.armor_class == 10
        assert stats.hit_points == 10
        assert stats.max_hit_points == 10
        assert stats.attacks == []
        assert stats.special_abilities == []
        assert stats.spells is None
        assert stats.challenge_rating == 1.0

    def test_custom_values(self):
        """Test stat block with custom values."""
        stats = NPCStatBlock(
            armor_class=15,
            hit_points=45,
            max_hit_points=45,
            attacks=[
                {"name": "Longsword", "bonus": 5, "damage": "1d8+3", "type": "slashing"}
            ],
            challenge_rating=3.0,
        )
        assert stats.armor_class == 15
        assert stats.hit_points == 45
        assert len(stats.attacks) == 1
        assert stats.attacks[0]["name"] == "Longsword"

    def test_with_spells(self):
        """Test stat block with spells."""
        stats = NPCStatBlock(
            spells={
                "0": ["Fire Bolt", "Ray of Frost"],
                "1": ["Magic Missile", "Shield"],
            }
        )
        assert "0" in stats.spells
        assert "Fire Bolt" in stats.spells["0"]


class TestNPCPersonality:
    """Test NPCPersonality model."""

    def test_default_values(self):
        """Test default personality values."""
        personality = NPCPersonality()
        assert personality.personality_traits == []
        assert personality.combat_style == "balanced"
        assert personality.aggression_level == 0.5
        assert personality.retreat_threshold == 0.25
        assert personality.speech_style == "normal"

    def test_aggressive_personality(self):
        """Test aggressive personality."""
        personality = NPCPersonality(
            personality_traits=["hot-tempered", "proud"],
            combat_style="aggressive",
            aggression_level=0.9,
            retreat_threshold=0.1,
        )
        assert personality.combat_style == "aggressive"
        assert personality.aggression_level == 0.9
        assert len(personality.personality_traits) == 2

    def test_with_catchphrases(self):
        """Test personality with catchphrases."""
        personality = NPCPersonality(
            catchphrases=["You dare challenge me?", "Feel my wrath!"]
        )
        assert len(personality.catchphrases) == 2

    def test_with_secrets(self):
        """Test personality with secrets."""
        personality = NPCPersonality(
            secrets=["Is secretly a vampire"]
        )
        assert "Is secretly a vampire" in personality.secrets


class TestNPCDiscordConfig:
    """Test NPCDiscordConfig model."""

    def test_minimal_config(self):
        """Test minimal Discord config."""
        config = NPCDiscordConfig(
            npc_id="npc_123",
            discord_bot_token="token123",
            discord_application_id="app123",
        )
        assert config.npc_id == "npc_123"
        assert config.discord_bot_token == "token123"
        assert config.active is True  # Default

    def test_full_config(self):
        """Test full Discord config."""
        config = NPCDiscordConfig(
            npc_id="npc_123",
            discord_bot_token="token123",
            discord_application_id="app123",
            discord_guild_ids=["guild1", "guild2"],
            display_name="Grom the Warrior",
            avatar_url="https://example.com/avatar.png",
            status_message="Guarding the tavern",
            active=True,
        )
        assert len(config.discord_guild_ids) == 2
        assert config.display_name == "Grom the Warrior"


class TestNPCFullProfile:
    """Test NPCFullProfile model."""

    def test_minimal_profile(self):
        """Test minimal NPC profile."""
        profile = NPCFullProfile(
            entity_id="npc_123",
            name="Grom",
        )
        assert profile.name == "Grom"
        assert profile.race == "human"  # Default
        assert profile.role == "commoner"  # Default
        assert profile.stat_block is not None
        assert profile.personality is not None

    def test_full_profile(self):
        """Test full NPC profile."""
        profile = NPCFullProfile(
            entity_id="npc_123",
            name="Grom",
            race="orc",
            role="warrior",
            description="A fierce orc warrior",
            stat_block=NPCStatBlock(armor_class=16, hit_points=52),
            personality=NPCPersonality(combat_style="aggressive"),
            current_hp=40,
            conditions=["wounded"],
            allied_with=["Orcish Horde"],
            hostile_to=["Village Guard"],
        )
        assert profile.race == "orc"
        assert profile.stat_block.armor_class == 16
        assert profile.personality.combat_style == "aggressive"
        assert profile.current_hp == 40
        assert "wounded" in profile.conditions


class TestCombatActionType:
    """Test CombatActionType enum."""

    def test_action_types(self):
        """Test action type values."""
        assert CombatActionType.ATTACK.value == "attack"
        assert CombatActionType.FLEE.value == "flee"
        assert CombatActionType.SURRENDER.value == "surrender"

    def test_all_actions_exist(self):
        """Test all expected actions exist."""
        actions = [
            "attack", "cast_spell", "use_ability", "move", "dash",
            "dodge", "disengage", "help", "hide", "ready", "use_item",
            "multiattack", "flee", "surrender", "dialogue",
        ]
        for action in actions:
            assert CombatActionType(action) is not None


class TestNPCCombatDecision:
    """Test NPCCombatDecision model."""

    def test_attack_decision(self):
        """Test attack decision."""
        decision = NPCCombatDecision(
            npc_id="npc_123",
            round=2,
            action_type=CombatActionType.ATTACK,
            action_name="Longsword",
            target_name="Thorin",
            reasoning="Thorin is the nearest threat.",
            combat_dialogue="Feel my blade!",
            rolls_needed=[
                {"type": "attack", "expression": "1d20+5"},
                {"type": "damage", "expression": "1d8+3"},
            ],
        )
        assert decision.action_type == CombatActionType.ATTACK
        assert decision.target_name == "Thorin"
        assert len(decision.rolls_needed) == 2

    def test_flee_decision(self):
        """Test flee decision."""
        decision = NPCCombatDecision(
            npc_id="npc_123",
            round=5,
            action_type=CombatActionType.FLEE,
            reasoning="HP too low, retreat!",
            movement_description="Runs toward the exit",
        )
        assert decision.action_type == CombatActionType.FLEE
        assert decision.target_name is None


class TestNPCCombatResult:
    """Test NPCCombatResult model."""

    def test_hit_result(self):
        """Test successful hit result."""
        decision = NPCCombatDecision(
            npc_id="npc_123",
            round=1,
            action_type=CombatActionType.ATTACK,
            action_name="Greataxe",
            target_name="Hero",
            reasoning="Target the hero",
        )
        result = NPCCombatResult(
            npc_id="npc_123",
            npc_name="Orc Warrior",
            action=decision,
            attack_roll={"expression": "1d20+5", "total": 18, "roll": 13},
            damage_roll={"expression": "1d12+4", "total": 12},
            hit=True,
            damage_dealt=12,
            target_new_hp=23,
            narration="Orc Warrior strikes Hero with Greataxe for **12 damage**!",
        )
        assert result.hit is True
        assert result.damage_dealt == 12

    def test_miss_result(self):
        """Test miss result."""
        decision = NPCCombatDecision(
            npc_id="npc_123",
            round=1,
            action_type=CombatActionType.ATTACK,
            reasoning="Attack",
        )
        result = NPCCombatResult(
            npc_id="npc_123",
            npc_name="Goblin",
            action=decision,
            attack_roll={"expression": "1d20+3", "total": 8, "roll": 5},
            hit=False,
            narration="Goblin's attack misses!",
        )
        assert result.hit is False
        assert result.damage_dealt is None


class TestNPCTriggerType:
    """Test NPCTriggerType enum."""

    def test_trigger_types(self):
        """Test trigger type values."""
        assert NPCTriggerType.DIRECT_MENTION.value == "direct_mention"
        assert NPCTriggerType.NAME_REFERENCE.value == "name_reference"
        assert NPCTriggerType.COMBAT_TURN.value == "combat_turn"
        assert NPCTriggerType.DM_COMMAND.value == "dm_command"
