"""Tests for combat manager."""

import pytest

from backend.discord.combat_manager import (
    CombatManager,
    CombatConfig,
    TurnType,
    TurnResult,
)
from backend.discord.models import (
    NPCStatBlock,
    NPCPersonality,
    NPCFullProfile,
)


class TestCombatManager:
    """Test CombatManager class."""

    @pytest.fixture
    def manager(self):
        """Create combat manager instance."""
        return CombatManager()

    @pytest.fixture
    def sample_players(self):
        """Create sample player combatants."""
        return [
            {
                "name": "Thorin",
                "initiative_bonus": 2,
                "hp": 25,
                "max_hp": 25,
                "ac": 16,
                "player_id": "player_1",
                "player_name": "John",
            },
            {
                "name": "Legolas",
                "initiative_bonus": 4,
                "hp": 20,
                "max_hp": 20,
                "ac": 14,
                "player_id": "player_2",
                "player_name": "Jane",
            },
        ]

    @pytest.fixture
    def sample_npcs(self):
        """Create sample NPC combatants (no actual profiles, just IDs)."""
        return [
            {
                "name": "Orc Warrior",
                "npc_id": "npc_orc_1",
                "initiative_bonus": 1,
                "hp": 15,
                "max_hp": 15,
                "ac": 13,
            },
        ]

    @pytest.fixture
    def sample_monsters(self):
        """Create sample DM-controlled monsters."""
        return [
            {
                "name": "Goblin",
                "initiative_bonus": 2,
                "hp": 7,
                "max_hp": 7,
                "ac": 12,
            },
        ]

    @pytest.mark.asyncio
    async def test_start_combat(self, manager, sample_players, sample_npcs):
        """Test starting combat."""
        result = await manager.start_combat(
            players=sample_players,
            npcs=sample_npcs,
        )

        assert result["combat_started"] is True
        assert result["round"] == 1
        assert len(result["initiative_order"]) == 3
        assert result["current_turn"] is not None

    @pytest.mark.asyncio
    async def test_start_combat_with_monsters(
        self, manager, sample_players, sample_npcs, sample_monsters
    ):
        """Test starting combat with DM-controlled monsters."""
        result = await manager.start_combat(
            players=sample_players,
            npcs=sample_npcs,
            monsters=sample_monsters,
        )

        assert len(result["initiative_order"]) == 4

    @pytest.mark.asyncio
    async def test_get_current_turn(self, manager, sample_players, sample_npcs):
        """Test getting current turn info."""
        await manager.start_combat(players=sample_players, npcs=sample_npcs)

        turn = await manager.get_current_turn()

        assert turn is not None
        assert "combatant" in turn
        assert "turn_type" in turn
        assert "round" in turn

    @pytest.mark.asyncio
    async def test_turn_type_detection(self, manager, sample_players, sample_npcs):
        """Test that turn types are correctly identified."""
        await manager.start_combat(players=sample_players, npcs=sample_npcs)

        # Check each combatant
        for c in manager.dm_tools.combat_state.initiative_order:
            turn_type = manager._get_turn_type(c)

            if c.get("is_player"):
                assert turn_type == TurnType.PLAYER
            elif c["name"].lower() in manager._combatant_npc_ids:
                assert turn_type == TurnType.NPC
            else:
                assert turn_type == TurnType.MONSTER

    @pytest.mark.asyncio
    async def test_process_player_turn(self, manager):
        """Test processing a player's turn (awaits action)."""
        # Start combat with only players
        players = [
            {"name": "Hero", "initiative_bonus": 5, "hp": 30, "player_id": "p1"},
        ]
        monsters = [
            {"name": "Goblin", "initiative_bonus": 0, "hp": 5},
        ]

        await manager.start_combat(players=players, npcs=[], monsters=monsters)

        # Find whose turn it is
        turn_info = await manager.get_current_turn()

        if turn_info["turn_type"] == "player":
            result = await manager.process_current_turn()

            assert result is not None
            assert result.turn_type == TurnType.PLAYER
            assert result.awaiting_action is True

    @pytest.mark.asyncio
    async def test_apply_damage(self, manager, sample_players, sample_npcs):
        """Test applying damage to combatants."""
        await manager.start_combat(players=sample_players, npcs=sample_npcs)

        result = manager.apply_damage("Thorin", 10)

        assert result["name"] == "Thorin"
        assert result["damage_taken"] == 10
        assert result["current_hp"] == 15  # 25 - 10

    @pytest.mark.asyncio
    async def test_apply_healing(self, manager, sample_players, sample_npcs):
        """Test applying healing to combatants."""
        await manager.start_combat(players=sample_players, npcs=sample_npcs)

        # First damage
        manager.apply_damage("Thorin", 10)

        # Then heal
        result = manager.apply_healing("Thorin", 5)

        assert result["name"] == "Thorin"
        assert result["current_hp"] == 20  # 15 + 5

    @pytest.mark.asyncio
    async def test_healing_cap(self, manager, sample_players, sample_npcs):
        """Test that healing doesn't exceed max HP."""
        await manager.start_combat(players=sample_players, npcs=sample_npcs)

        # Damage a little
        manager.apply_damage("Thorin", 5)

        # Heal a lot
        result = manager.apply_healing("Thorin", 100)

        assert result["current_hp"] == 25  # Capped at max_hp

    @pytest.mark.asyncio
    async def test_add_condition(self, manager, sample_players, sample_npcs):
        """Test adding conditions to combatants."""
        await manager.start_combat(players=sample_players, npcs=sample_npcs)

        result = manager.add_condition("Thorin", "poisoned")

        assert "poisoned" in result["conditions"]

    @pytest.mark.asyncio
    async def test_remove_condition(self, manager, sample_players, sample_npcs):
        """Test removing conditions from combatants."""
        await manager.start_combat(players=sample_players, npcs=sample_npcs)

        manager.add_condition("Thorin", "poisoned")
        result = manager.remove_condition("Thorin", "poisoned")

        assert "poisoned" not in result["conditions"]

    @pytest.mark.asyncio
    async def test_combat_end_all_enemies_defeated(self, manager):
        """Test combat ends when all enemies are defeated."""
        players = [{"name": "Hero", "hp": 30, "player_id": "p1"}]
        monsters = [{"name": "Goblin", "hp": 5}]

        await manager.start_combat(players=players, npcs=[], monsters=monsters)

        # Kill the goblin
        result = manager.apply_damage("Goblin", 10)

        assert result.get("combat_ended") is True
        assert "enemies defeated" in result.get("end_reason", "").lower()

    @pytest.mark.asyncio
    async def test_get_combat_status(self, manager, sample_players, sample_npcs):
        """Test getting full combat status."""
        await manager.start_combat(players=sample_players, npcs=sample_npcs)

        status = manager.get_combat_status()

        assert status is not None
        assert "round" in status
        assert "current" in status
        assert "initiative_order" in status
        assert "current_turn_type" in status

    @pytest.mark.asyncio
    async def test_end_combat(self, manager, sample_players, sample_npcs):
        """Test ending combat manually."""
        await manager.start_combat(players=sample_players, npcs=sample_npcs)

        summary = await manager.end_combat()

        assert "rounds" in summary
        assert "survivors" in summary
        assert "defeated" in summary

        # Combat should no longer be active
        status = manager.get_combat_status()
        assert status is None


class TestCombatConfig:
    """Test CombatConfig."""

    def test_default_config(self):
        """Test default configuration values."""
        config = CombatConfig()

        assert config.auto_npc_turns is True
        assert config.announce_npc_turns is True
        assert config.auto_end_combat is True

    def test_custom_config(self):
        """Test custom configuration."""
        config = CombatConfig(
            auto_npc_turns=False,
            npc_turn_delay=1.0,
        )

        assert config.auto_npc_turns is False
        assert config.npc_turn_delay == 1.0


class TestTurnResult:
    """Test TurnResult model."""

    def test_player_turn_result(self):
        """Test player turn result."""
        result = TurnResult(
            combatant_name="Thorin",
            turn_type=TurnType.PLAYER,
            round=1,
            awaiting_action=True,
            suggested_actions=["Attack", "Cast spell"],
            narration="Thorin's turn",
        )

        assert result.turn_type == TurnType.PLAYER
        assert result.awaiting_action is True
        assert len(result.suggested_actions) == 2

    def test_npc_turn_result(self):
        """Test NPC turn result."""
        result = TurnResult(
            combatant_name="Orc",
            turn_type=TurnType.NPC,
            round=2,
            awaiting_action=False,
            narration="Orc attacks Thorin for 12 damage!",
        )

        assert result.turn_type == TurnType.NPC
        assert result.awaiting_action is False

    def test_combat_ended_result(self):
        """Test combat ended result."""
        result = TurnResult(
            combatant_name="",
            turn_type=TurnType.PLAYER,
            round=5,
            combat_active=False,
            combat_ended_reason="All enemies defeated",
            narration="Combat ended!",
        )

        assert result.combat_active is False
        assert result.combat_ended_reason is not None
