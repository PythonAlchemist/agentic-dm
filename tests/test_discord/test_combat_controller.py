"""Tests for NPC combat controller."""

import pytest

from backend.discord.models import (
    NPCDiscordConfig,
    NPCStatBlock,
    NPCPersonality,
    NPCFullProfile,
)
from backend.discord.combat_models import CombatActionType, NPCCombatDecision
from backend.discord.combat_controller import NPCCombatController
from backend.agents.tools import DMTools, CombatState


class TestNPCCombatController:
    """Test NPCCombatController class."""

    @pytest.fixture
    def controller(self):
        """Create combat controller instance."""
        return NPCCombatController()

    @pytest.fixture
    def dm_tools(self):
        """Create DMTools instance."""
        return DMTools()

    @pytest.fixture
    def sample_npc(self):
        """Create sample NPC for testing."""
        return NPCFullProfile(
            entity_id="npc_123",
            name="Orc Warrior",
            race="orc",
            role="warrior",
            stat_block=NPCStatBlock(
                armor_class=13,
                hit_points=15,
                max_hit_points=15,
                attacks=[
                    {"name": "Greataxe", "bonus": 5, "damage": "1d12+3", "type": "slashing"},
                ],
            ),
            personality=NPCPersonality(
                combat_style="aggressive",
                aggression_level=0.8,
                retreat_threshold=0.2,
            ),
        )

    def test_register_npc_combatant(self, controller, sample_npc):
        """Test registering an NPC combatant."""
        controller.register_npc_combatant("Orc Warrior", sample_npc.entity_id)

        # Verify registration
        combatant = {"name": "Orc Warrior", "is_player": False}
        assert controller.is_npc_turn(combatant) is True

    def test_is_npc_turn_player(self, controller):
        """Test that player turns are not NPC turns."""
        combatant = {
            "name": "Thorin",
            "is_player": True,
        }
        assert controller.is_npc_turn(combatant) is False

    def test_is_npc_turn_unregistered(self, controller):
        """Test that unregistered NPCs are not recognized."""
        combatant = {
            "name": "Random Monster",
            "is_player": False,
        }
        assert controller.is_npc_turn(combatant) is False

    def test_get_available_targets(self, controller, dm_tools):
        """Test getting available targets for an NPC."""
        # Start combat with some combatants
        combatants = [
            {"name": "Orc Warrior", "hp": 15, "max_hp": 15, "is_player": False},
            {"name": "Thorin", "hp": 20, "max_hp": 25, "is_player": True},
            {"name": "Legolas", "hp": 18, "max_hp": 18, "is_player": True},
            {"name": "Dead Guy", "hp": 0, "max_hp": 10, "is_player": True},
        ]
        combat_state = dm_tools.start_combat(combatants)

        controller._npc_combatant_map["orc warrior"] = "npc_123"

        npc_combatant = combatants[0]
        targets = controller.get_available_targets(npc_combatant, combat_state)

        # Should only include living players
        assert len(targets) == 2
        target_names = [t["name"] for t in targets]
        assert "Thorin" in target_names
        assert "Legolas" in target_names
        assert "Dead Guy" not in target_names
        assert "Orc Warrior" not in target_names

    def test_roll_dice(self, controller):
        """Test dice rolling through controller."""
        result = controller._roll_dice("1d20+5")

        assert "expression" in result
        assert "rolls" in result
        assert "total" in result
        assert 6 <= result["total"] <= 25

    def test_generate_hit_narration(self, controller, sample_npc):
        """Test hit narration generation."""
        decision = NPCCombatDecision(
            npc_id="npc_123",
            round=1,
            action_type=CombatActionType.ATTACK,
            action_name="Greataxe",
            target_name="Thorin",
            reasoning="Attack",
        )

        narration = controller._generate_hit_narration(
            npc=sample_npc,
            decision=decision,
            damage=12,
            target_hp=8,
        )

        assert "Orc Warrior" in narration
        assert "Thorin" in narration
        assert "12" in narration
        assert "damage" in narration.lower()

    def test_generate_hit_narration_kills_target(self, controller, sample_npc):
        """Test hit narration when target goes down."""
        decision = NPCCombatDecision(
            npc_id="npc_123",
            round=1,
            action_type=CombatActionType.ATTACK,
            action_name="Greataxe",
            target_name="Thorin",
            reasoning="Attack",
        )

        narration = controller._generate_hit_narration(
            npc=sample_npc,
            decision=decision,
            damage=20,
            target_hp=0,
        )

        assert "goes down" in narration.lower()

    def test_generate_miss_narration(self, controller, sample_npc):
        """Test miss narration generation."""
        decision = NPCCombatDecision(
            npc_id="npc_123",
            round=1,
            action_type=CombatActionType.ATTACK,
            action_name="Greataxe",
            target_name="Thorin",
            reasoning="Attack",
        )

        narration = controller._generate_miss_narration(
            npc=sample_npc,
            decision=decision,
        )

        assert "Orc Warrior" in narration
        assert "Thorin" in narration

    def test_set_combat_channel(self, controller):
        """Test setting combat broadcast channel."""
        controller.set_combat_channel(12345)
        assert controller._combat_channel_id == 12345

    def test_clear_combat(self, controller, sample_npc):
        """Test clearing combat state."""
        controller.register_npc_combatant("Orc Warrior", sample_npc.entity_id)
        controller.set_combat_channel(12345)

        controller.clear_combat()

        assert len(controller._npc_combatant_map) == 0
        assert controller._combat_channel_id is None


class TestCombatIntegration:
    """Integration tests for combat flow."""

    @pytest.fixture
    def controller(self):
        """Create combat controller with tools."""
        return NPCCombatController()

    def test_full_combat_turn_detection(self, controller):
        """Test detecting NPC turns in combat."""
        # Set up combat
        combatants = [
            {"name": "Thorin", "hp": 20, "max_hp": 25, "initiative_bonus": 2, "is_player": True},
            {"name": "Orc Chief", "hp": 30, "max_hp": 30, "initiative_bonus": 1, "is_player": False},
        ]

        combat_state = controller.dm_tools.start_combat(combatants)

        # Register the NPC
        controller.register_npc_combatant("Orc Chief", "npc_orc_chief")

        # Find the Orc Chief in initiative
        for combatant in combat_state.initiative_order:
            if combatant["name"] == "Orc Chief":
                assert controller.is_npc_turn(combatant) is True
            else:
                assert controller.is_npc_turn(combatant) is False
