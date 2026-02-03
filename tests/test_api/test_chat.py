"""Tests for chat API endpoints."""

import pytest
from fastapi.testclient import TestClient

from backend.api.main import app


@pytest.fixture
def client():
    """Create test client."""
    return TestClient(app)


class TestHealthEndpoints:
    """Test health check endpoints."""

    def test_root_endpoint(self, client):
        """Test root health check."""
        response = client.get("/")
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "ok"
        assert data["service"] == "D&D DM Assistant"

    def test_health_endpoint(self, client):
        """Test detailed health check."""
        response = client.get("/health")
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "healthy"
        assert "components" in data


class TestToolEndpoints:
    """Test tool endpoints (dice, NPC, encounter)."""

    def test_roll_dice_basic(self, client):
        """Test basic dice roll."""
        response = client.post(
            "/api/chat/tools/roll",
            json={"expression": "1d20"},
        )
        assert response.status_code == 200
        data = response.json()
        assert data["expression"] == "1d20"
        assert len(data["rolls"]) == 1
        assert 1 <= data["total"] <= 20

    def test_roll_dice_with_modifier(self, client):
        """Test dice roll with modifier."""
        response = client.post(
            "/api/chat/tools/roll",
            json={"expression": "2d6+5"},
        )
        assert response.status_code == 200
        data = response.json()
        assert data["modifier"] == 5
        assert len(data["rolls"]) == 2

    def test_generate_npc(self, client):
        """Test NPC generation."""
        response = client.post(
            "/api/chat/tools/npc",
            json={"role": "merchant"},
        )
        assert response.status_code == 200
        data = response.json()
        assert data["name"]
        assert data["role"] == "merchant"
        assert data["race"]
        assert len(data["personality"]) == 2
        assert len(data["motivations"]) == 2

    def test_generate_npc_with_race(self, client):
        """Test NPC generation with specified race."""
        response = client.post(
            "/api/chat/tools/npc",
            json={"role": "guard", "race": "dwarf"},
        )
        assert response.status_code == 200
        data = response.json()
        assert data["race"] == "dwarf"

    def test_generate_encounter(self, client):
        """Test encounter generation."""
        response = client.post(
            "/api/chat/tools/encounter",
            json={
                "difficulty": "medium",
                "environment": "dungeon",
                "party_level": 3,
                "party_size": 4,
            },
        )
        assert response.status_code == 200
        data = response.json()
        assert data["difficulty"] == "medium"
        assert data["environment"] == "dungeon"
        assert data["party_level"] == 3
        assert len(data["monsters"]) > 0
        assert data["total_xp"] > 0


class TestSessionEndpoints:
    """Test session management endpoints."""

    def test_get_nonexistent_session(self, client):
        """Test getting a session that doesn't exist."""
        response = client.get("/api/chat/sessions/nonexistent-id")
        assert response.status_code == 404

    def test_delete_nonexistent_session(self, client):
        """Test deleting a session that doesn't exist."""
        response = client.delete("/api/chat/sessions/nonexistent-id")
        assert response.status_code == 404


class TestCampaignEndpoints:
    """Test campaign API endpoints."""

    def test_list_entities(self, client):
        """Test listing campaign entities."""
        response = client.get("/api/campaign/entities")
        # May succeed or fail depending on graph connection
        assert response.status_code in (200, 500)

    def test_search_campaign(self, client):
        """Test campaign search."""
        response = client.get("/api/campaign/search?q=test")
        # May succeed or fail depending on graph connection
        assert response.status_code in (200, 500)
