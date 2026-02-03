"""Player management endpoints."""

from typing import Optional

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from backend.graph.operations import CampaignGraphOps

router = APIRouter()

_graph_ops: Optional[CampaignGraphOps] = None


def get_graph_ops() -> CampaignGraphOps:
    """Get or create graph operations instance."""
    global _graph_ops
    if _graph_ops is None:
        _graph_ops = CampaignGraphOps()
    return _graph_ops


# ===================
# Request/Response Models
# ===================


class PlayerCreate(BaseModel):
    """Player creation model."""

    name: str
    email: Optional[str] = None
    discord_id: Optional[str] = None


class PlayerUpdate(BaseModel):
    """Player update model."""

    name: Optional[str] = None
    email: Optional[str] = None
    discord_id: Optional[str] = None
    active_pc_id: Optional[str] = None
    notes: Optional[str] = None


class PlayerResponse(BaseModel):
    """Player response model."""

    id: str
    name: str
    email: Optional[str] = None
    discord_id: Optional[str] = None
    joined_at: Optional[str] = None
    active_pc_id: Optional[str] = None
    active_pc: Optional[dict] = None
    characters: list[dict] = Field(default_factory=list)


class CharacterCreate(BaseModel):
    """Character creation model."""

    name: str
    character_class: str
    level: int = 1
    race: Optional[str] = None
    hp: Optional[int] = None
    max_hp: Optional[int] = None
    initiative_bonus: int = 0
    description: Optional[str] = None


class ActiveCharacterUpdate(BaseModel):
    """Active character update model."""

    pc_id: str


class CampaignCreate(BaseModel):
    """Campaign creation model."""

    name: str
    setting: Optional[str] = None
    description: Optional[str] = None


class SessionCreate(BaseModel):
    """Session creation model."""

    session_number: int
    name: Optional[str] = None
    date: Optional[str] = None
    summary: Optional[str] = None


class SessionAttendance(BaseModel):
    """Session attendance model."""

    player_ids: list[str]
    character_ids: Optional[list[str]] = None


class AddPlayerToCampaign(BaseModel):
    """Add player to campaign model."""

    player_id: str


# ===================
# Player CRUD
# ===================


@router.post("/players", response_model=PlayerResponse)
async def create_player(player: PlayerCreate) -> PlayerResponse:
    """Create a new player."""
    try:
        ops = get_graph_ops()
        created = ops.create_player(
            name=player.name,
            email=player.email,
            discord_id=player.discord_id,
        )
        # Get full player with characters
        full_player = ops.get_player(created["id"])
        return PlayerResponse(**full_player)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/players", response_model=list[PlayerResponse])
async def list_players(
    campaign_id: Optional[str] = Query(None, description="Filter by campaign"),
) -> list[PlayerResponse]:
    """List all players."""
    try:
        ops = get_graph_ops()
        if campaign_id:
            players = ops.get_campaign_players(campaign_id)
        else:
            players = ops.list_players()
            # Enrich with character data
            for player in players:
                chars = ops.get_player_characters(player["id"])
                player["characters"] = chars
                active_pc_id = player.get("active_pc_id")
                if active_pc_id:
                    player["active_pc"] = next(
                        (c for c in chars if c["id"] == active_pc_id), None
                    )
                else:
                    player["active_pc"] = chars[0] if chars else None
        return [PlayerResponse(**p) for p in players]
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/players/{player_id}", response_model=PlayerResponse)
async def get_player(player_id: str) -> PlayerResponse:
    """Get a specific player by ID."""
    try:
        ops = get_graph_ops()
        player = ops.get_player(player_id)
        if not player:
            raise HTTPException(status_code=404, detail="Player not found")
        return PlayerResponse(**player)
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.put("/players/{player_id}", response_model=PlayerResponse)
async def update_player(player_id: str, update: PlayerUpdate) -> PlayerResponse:
    """Update a player."""
    try:
        ops = get_graph_ops()
        player = ops.get_entity(player_id)
        if not player:
            raise HTTPException(status_code=404, detail="Player not found")

        # Build update dict, excluding None values
        update_data = {k: v for k, v in update.model_dump().items() if v is not None}
        if update_data:
            ops.update_entity(player_id, update_data)

        updated = ops.get_player(player_id)
        return PlayerResponse(**updated)
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.delete("/players/{player_id}")
async def delete_player(player_id: str) -> dict:
    """Delete a player."""
    try:
        ops = get_graph_ops()
        player = ops.get_entity(player_id)
        if not player:
            raise HTTPException(status_code=404, detail="Player not found")

        ops.delete_entity(player_id)
        return {"success": True, "player_id": player_id}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ===================
# Player Characters
# ===================


@router.post("/players/{player_id}/characters")
async def create_character(player_id: str, character: CharacterCreate) -> dict:
    """Create a new character for a player."""
    try:
        ops = get_graph_ops()
        player = ops.get_entity(player_id)
        if not player:
            raise HTTPException(status_code=404, detail="Player not found")

        pc = ops.create_player_character(
            player_id=player_id,
            name=character.name,
            character_class=character.character_class,
            level=character.level,
            race=character.race,
            hp=character.hp,
            max_hp=character.max_hp,
            initiative_bonus=character.initiative_bonus,
            description=character.description,
        )
        return pc
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/players/{player_id}/characters")
async def get_player_characters(player_id: str) -> list[dict]:
    """Get all characters for a player."""
    try:
        ops = get_graph_ops()
        player = ops.get_entity(player_id)
        if not player:
            raise HTTPException(status_code=404, detail="Player not found")

        return ops.get_player_characters(player_id)
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.put("/players/{player_id}/active-character", response_model=PlayerResponse)
async def set_active_character(
    player_id: str, update: ActiveCharacterUpdate
) -> PlayerResponse:
    """Set the active character for a player."""
    try:
        ops = get_graph_ops()
        player = ops.get_entity(player_id)
        if not player:
            raise HTTPException(status_code=404, detail="Player not found")

        # Verify character belongs to player
        characters = ops.get_player_characters(player_id)
        if not any(c["id"] == update.pc_id for c in characters):
            raise HTTPException(
                status_code=400,
                detail="Character does not belong to this player",
            )

        updated = ops.set_active_character(player_id, update.pc_id)
        return PlayerResponse(**updated)
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ===================
# Campaigns
# ===================


@router.post("/campaigns")
async def create_campaign(campaign: CampaignCreate) -> dict:
    """Create a new campaign."""
    try:
        ops = get_graph_ops()
        return ops.create_campaign(
            name=campaign.name,
            setting=campaign.setting,
            description=campaign.description,
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/campaigns/{campaign_id}/players")
async def get_campaign_players(campaign_id: str) -> list[dict]:
    """Get all players in a campaign."""
    try:
        ops = get_graph_ops()
        return ops.get_campaign_players(campaign_id)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/campaigns/{campaign_id}/players")
async def add_player_to_campaign(campaign_id: str, data: AddPlayerToCampaign) -> dict:
    """Add a player to a campaign."""
    try:
        ops = get_graph_ops()

        # Verify campaign exists
        campaign = ops.get_entity(campaign_id)
        if not campaign:
            raise HTTPException(status_code=404, detail="Campaign not found")

        # Verify player exists
        player = ops.get_entity(data.player_id)
        if not player:
            raise HTTPException(status_code=404, detail="Player not found")

        ops.add_player_to_campaign(data.player_id, campaign_id)
        return {"success": True, "player_id": data.player_id, "campaign_id": campaign_id}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.delete("/campaigns/{campaign_id}/players/{player_id}")
async def remove_player_from_campaign(campaign_id: str, player_id: str) -> dict:
    """Remove a player from a campaign."""
    try:
        ops = get_graph_ops()

        # Delete the BELONGS_TO relationship
        query = """
        MATCH (p:Entity {id: $player_id})-[r:BELONGS_TO]->(c:Entity {id: $campaign_id})
        DELETE r
        RETURN count(r) as deleted
        """
        from backend.core.database import neo4j_session

        with neo4j_session() as session:
            result = session.run(query, player_id=player_id, campaign_id=campaign_id)
            record = result.single()
            if record["deleted"] == 0:
                raise HTTPException(
                    status_code=404,
                    detail="Player not in campaign",
                )

        return {"success": True, "player_id": player_id, "campaign_id": campaign_id}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ===================
# Sessions
# ===================


@router.post("/campaigns/{campaign_id}/sessions")
async def create_session(campaign_id: str, session_data: SessionCreate) -> dict:
    """Create a new session for a campaign."""
    try:
        ops = get_graph_ops()

        # Verify campaign exists
        campaign = ops.get_entity(campaign_id)
        if not campaign:
            raise HTTPException(status_code=404, detail="Campaign not found")

        return ops.create_session(
            campaign_id=campaign_id,
            session_number=session_data.session_number,
            name=session_data.name,
            date=session_data.date,
            summary=session_data.summary,
        )
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/sessions/{session_id}/attendance")
async def record_session_attendance(
    session_id: str, attendance: SessionAttendance
) -> dict:
    """Record which players attended a session."""
    try:
        ops = get_graph_ops()

        # Verify session exists
        session = ops.get_entity(session_id)
        if not session:
            raise HTTPException(status_code=404, detail="Session not found")

        return ops.record_session_attendance(
            session_id=session_id,
            player_ids=attendance.player_ids,
            character_ids=attendance.character_ids,
        )
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/sessions/{session_id}/attendance")
async def get_session_attendance(session_id: str) -> list[dict]:
    """Get which players attended a session."""
    try:
        ops = get_graph_ops()

        # Verify session exists
        session = ops.get_entity(session_id)
        if not session:
            raise HTTPException(status_code=404, detail="Session not found")

        return ops.get_session_attendees(session_id)
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
