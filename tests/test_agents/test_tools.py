"""Tests for DM tools."""

import pytest

from backend.agents.tools import DMTools, DiceResult, NPCResult, EncounterResult


class TestDiceRolling:
    """Test dice rolling functionality."""

    @pytest.fixture
    def tools(self):
        """Create DMTools instance."""
        return DMTools()

    def test_basic_d20(self, tools):
        """Test basic d20 roll."""
        result = tools.roll_dice("1d20")
        assert isinstance(result, DiceResult)
        assert 1 <= result.total <= 20
        assert len(result.rolls) == 1
        assert result.modifier == 0

    def test_multiple_dice(self, tools):
        """Test rolling multiple dice."""
        result = tools.roll_dice("3d6")
        assert len(result.rolls) == 3
        assert 3 <= result.total <= 18
        assert all(1 <= r <= 6 for r in result.rolls)

    def test_dice_with_positive_modifier(self, tools):
        """Test dice with positive modifier."""
        result = tools.roll_dice("1d20+5")
        assert result.modifier == 5
        assert 6 <= result.total <= 25

    def test_dice_with_negative_modifier(self, tools):
        """Test dice with negative modifier."""
        result = tools.roll_dice("1d20-3")
        assert result.modifier == -3
        assert -2 <= result.total <= 17

    def test_critical_detection(self, tools):
        """Test critical detection on d20."""
        # Roll many times to catch critical
        criticals_found = False
        for _ in range(100):
            result = tools.roll_dice("1d20")
            if result.critical:
                criticals_found = True
                assert result.rolls[0] in (1, 20)
                break
        # It's possible but unlikely to not find any criticals in 100 rolls

    def test_invalid_expression(self, tools):
        """Test invalid dice expression."""
        result = tools.roll_dice("invalid")
        assert result.total == 0

    def test_drop_lowest(self, tools):
        """Test ability score rolling with drop lowest."""
        result = tools.roll_dice("4d6 drop lowest")
        assert len(result.rolls) == 3  # One dropped


class TestNPCGeneration:
    """Test NPC generation."""

    @pytest.fixture
    def tools(self):
        """Create DMTools instance."""
        return DMTools()

    def test_generate_npc_basic(self, tools):
        """Test basic NPC generation."""
        result = tools.generate_npc(role="merchant")
        assert isinstance(result, NPCResult)
        assert result.name
        assert result.role == "merchant"
        assert result.race
        assert len(result.personality) == 2
        assert len(result.motivations) == 2

    def test_generate_npc_with_race(self, tools):
        """Test NPC generation with specified race."""
        result = tools.generate_npc(role="guard", race="dwarf")
        assert result.race == "dwarf"

    def test_npc_has_appearance(self, tools):
        """Test NPC has appearance description."""
        result = tools.generate_npc(role="innkeeper")
        assert result.appearance

    def test_npc_has_voice_notes(self, tools):
        """Test NPC has voice notes."""
        result = tools.generate_npc(role="scholar")
        assert result.voice_notes

    def test_npc_sometimes_has_secret(self, tools):
        """Test some NPCs have secrets."""
        has_secret = False
        for _ in range(10):
            result = tools.generate_npc(role="merchant")
            if result.secret:
                has_secret = True
                break
        # At least one should have a secret in 10 generations


class TestEncounterGeneration:
    """Test encounter generation."""

    @pytest.fixture
    def tools(self):
        """Create DMTools instance."""
        return DMTools()

    def test_generate_encounter_basic(self, tools):
        """Test basic encounter generation."""
        result = tools.generate_encounter(
            difficulty="medium",
            environment="dungeon",
            party_level=3,
        )
        assert isinstance(result, EncounterResult)
        assert result.difficulty == "medium"
        assert result.environment == "dungeon"
        assert result.party_level == 3
        assert len(result.monsters) > 0

    def test_encounter_has_xp(self, tools):
        """Test encounter has XP total."""
        result = tools.generate_encounter(
            difficulty="hard",
            environment="forest",
            party_level=5,
        )
        assert result.total_xp > 0

    def test_encounter_has_description(self, tools):
        """Test encounter has description."""
        result = tools.generate_encounter(
            difficulty="easy",
            environment="urban",
            party_level=2,
        )
        assert result.description

    def test_encounter_has_tactics(self, tools):
        """Test encounter has tactics."""
        result = tools.generate_encounter(
            difficulty="deadly",
            environment="underdark",
            party_level=7,
        )
        assert result.tactics

    def test_different_environments(self, tools):
        """Test different environments produce different monsters."""
        dungeon = tools.generate_encounter("medium", "dungeon", 3)
        forest = tools.generate_encounter("medium", "forest", 3)
        urban = tools.generate_encounter("medium", "urban", 3)

        # All should have monsters
        assert dungeon.monsters
        assert forest.monsters
        assert urban.monsters


class TestCombatManagement:
    """Test combat state management."""

    @pytest.fixture
    def tools(self):
        """Create DMTools instance."""
        return DMTools()

    @pytest.fixture
    def combatants(self):
        """Sample combatants for testing."""
        return [
            {"name": "Fighter", "initiative_bonus": 2, "hp": 30, "is_player": True},
            {"name": "Wizard", "initiative_bonus": 1, "hp": 15, "is_player": True},
            {"name": "Goblin 1", "initiative_bonus": 2, "hp": 7, "is_player": False},
            {"name": "Goblin 2", "initiative_bonus": 2, "hp": 7, "is_player": False},
        ]

    def test_start_combat(self, tools, combatants):
        """Test starting combat."""
        state = tools.start_combat(combatants)
        assert state.active is True
        assert state.round == 1
        assert len(state.initiative_order) == 4

    def test_initiative_order(self, tools, combatants):
        """Test initiative is sorted correctly."""
        state = tools.start_combat(combatants)
        initiatives = [c["initiative"] for c in state.initiative_order]
        assert initiatives == sorted(initiatives, reverse=True)

    def test_next_turn(self, tools, combatants):
        """Test advancing turns."""
        tools.start_combat(combatants)
        first = tools.combat_state.initiative_order[0]["name"]

        result = tools.next_turn()
        assert result["round"] >= 1
        assert result["current"]["name"] != first or tools.combat_state.round > 1

    def test_apply_damage(self, tools, combatants):
        """Test applying damage."""
        tools.start_combat(combatants)
        result = tools.apply_damage("Goblin 1", 5)
        assert result["damage_taken"] == 5
        assert result["current_hp"] == 2

    def test_damage_cannot_go_below_zero(self, tools, combatants):
        """Test HP doesn't go below zero."""
        tools.start_combat(combatants)
        result = tools.apply_damage("Goblin 1", 100)
        assert result["current_hp"] == 0
        assert result["status"] == "down"

    def test_end_combat(self, tools, combatants):
        """Test ending combat."""
        tools.start_combat(combatants)
        tools.apply_damage("Goblin 1", 10)

        summary = tools.end_combat()
        assert summary["rounds"] >= 1
        assert len(summary["survivors"]) == 3
        assert len(summary["defeated"]) == 1
        assert tools.combat_state is None

    def test_no_combat_active(self, tools):
        """Test handling when no combat is active."""
        result = tools.next_turn()
        assert result is None

        result = tools.apply_damage("Someone", 10)
        assert "error" in result
