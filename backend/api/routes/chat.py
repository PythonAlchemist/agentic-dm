"""Chat endpoint for DM Assistant interactions."""

from collections import OrderedDict
from typing import Optional
from uuid import uuid4

from fastapi import APIRouter, HTTPException, WebSocket, WebSocketDisconnect
from pydantic import BaseModel, Field

from backend.agents import DMAgent, DMResponse

router = APIRouter()

#: How many conversations this router keeps. The same cap and the same reason
#: as `lab._MAX_SESSIONS`, which is the store the web app actually reaches.
_MAX_SESSIONS = 64

#: Session storage, oldest use first.
#:
#: NOTHING REACHES THIS ROUTER TODAY. The web app posts to `/api/lab/chat` --
#: `api.ts` prefixes `/lab` -- so these routes and the WebSocket beside them
#: are unused, and the WebSocket cannot be reached from a browser at all, which
#: cannot set an `Authorization` header on a handshake. It is left in place
#: because a non-browser client CAN, so this is dead surface rather than a dead
#: capability, and deleting a public API is not a tidy-up.
#:
#: BOUNDED ANYWAY, because "nothing calls it" is a fact about today. This held
#: an unbounded dict of agents, each carrying a conversation, with nothing ever
#: releasing them -- the same leak `lab` had while every client called its
#: session `'lab'` and the dict happened to hold exactly one.
_sessions: OrderedDict[str, DMAgent] = OrderedDict()


def get_or_create_session(
    session_id: Optional[str] = None,
    campaign_id: Optional[str] = None,
    campaign_context: Optional[dict] = None,
) -> tuple[str, DMAgent]:
    """Get existing session or create new one.

    Args:
        session_id: Optional existing session ID.
        campaign_id: Optional campaign ID.
        campaign_context: Optional campaign context for prompt enrichment.

    Returns:
        Tuple of (session_id, DMAgent).
    """
    if session_id and session_id in _sessions:
        # A READ IS A USE, or the cap evicts by age of creation and drops the
        # session of whoever has been talking longest.
        _sessions.move_to_end(session_id)
        return session_id, _sessions[session_id]

    # Create new session
    new_id = session_id or str(uuid4())
    agent = DMAgent(campaign_id=campaign_id, campaign_context=campaign_context)
    _sessions[new_id] = agent
    _sessions.move_to_end(new_id)
    while len(_sessions) > _MAX_SESSIONS:
        _sessions.popitem(last=False)

    return new_id, agent


def _load_campaign_context(campaign_id: str) -> Optional[dict]:
    """Load campaign context from the knowledge graph.

    Args:
        campaign_id: Campaign entity ID.

    Returns:
        Campaign context dict or None.
    """
    try:
        from backend.graph.operations import CampaignGraphOps
        ops = CampaignGraphOps()
        campaign = ops.get_entity(campaign_id)
        if campaign and campaign.get("entity_type") == "CAMPAIGN":
            return campaign
    except Exception:
        pass
    return None


class ChatMessage(BaseModel):
    """A single chat message."""

    role: str  # "user" or "assistant"
    content: str


class ChatRequest(BaseModel):
    """Chat request payload."""

    message: str
    session_id: Optional[str] = None
    campaign_id: Optional[str] = None


class ChatResponse(BaseModel):
    """Chat response payload."""

    response: str
    session_id: str
    query_type: Optional[str] = None
    sources: list[dict] = Field(default_factory=list)
    tool_results: list[dict] = Field(default_factory=list)
    suggestions: list[str] = Field(default_factory=list)


class SessionInfo(BaseModel):
    """Session information."""

    session_id: str
    message_count: int
    campaign_id: Optional[str] = None


class DiceRollRequest(BaseModel):
    """Dice roll request."""

    expression: str  # e.g., "2d6+3"


class DiceRollResponse(BaseModel):
    """Dice roll response."""

    expression: str
    rolls: list[int]
    modifier: int
    total: int
    critical: bool


class NPCRequest(BaseModel):
    """NPC generation request."""

    role: str
    race: Optional[str] = None


class EncounterRequest(BaseModel):
    """Encounter generation request."""

    difficulty: str = "medium"
    environment: str = "dungeon"
    party_level: int = 3
    party_size: int = 4


@router.post("/", response_model=ChatResponse)
async def chat(request: ChatRequest) -> ChatResponse:
    """Process a chat message and return DM response.

    This endpoint supports:
    - Session management (persistent conversation)
    - Tool commands (dice rolling, NPC/encounter generation)
    - RAG-powered context retrieval
    - Campaign context injection
    """
    try:
        # Load campaign context if campaign_id provided
        campaign_context = None
        if request.campaign_id:
            campaign_context = _load_campaign_context(request.campaign_id)

        session_id, agent = get_or_create_session(
            session_id=request.session_id,
            campaign_id=request.campaign_id,
            campaign_context=campaign_context,
        )

        # Process the message
        result: DMResponse = await agent.process_message(
            user_input=request.message,
        )

        return ChatResponse(
            response=result.message,
            session_id=session_id,
            query_type=result.query_type.value if result.query_type else None,
            sources=result.sources,
            tool_results=result.tool_results,
            suggestions=result.suggestions,
        )

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/simple")
async def simple_chat(message: str) -> dict:
    """Simple chat endpoint for quick testing.

    Creates a temporary session for single-turn interactions.
    """
    try:
        agent = DMAgent()
        result = await agent.process_message(message)
        return {"response": result.message}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/sessions/{session_id}", response_model=SessionInfo)
async def get_session(session_id: str) -> SessionInfo:
    """Get session information."""
    if session_id not in _sessions:
        raise HTTPException(status_code=404, detail="Session not found")

    agent = _sessions[session_id]
    return SessionInfo(
        session_id=session_id,
        message_count=len(agent.conversation.messages),
        campaign_id=agent.campaign_id,
    )


@router.delete("/sessions/{session_id}")
async def delete_session(session_id: str) -> dict:
    """Delete a session."""
    if session_id not in _sessions:
        raise HTTPException(status_code=404, detail="Session not found")

    del _sessions[session_id]
    return {"success": True, "session_id": session_id}


@router.get("/sessions/{session_id}/history")
async def get_session_history(session_id: str) -> dict:
    """Get conversation history for a session."""
    if session_id not in _sessions:
        raise HTTPException(status_code=404, detail="Session not found")

    agent = _sessions[session_id]
    return {
        "session_id": session_id,
        "history": agent.get_conversation_history(),
    }


@router.post("/sessions/{session_id}/clear")
async def clear_session_history(session_id: str) -> dict:
    """Clear conversation history for a session."""
    if session_id not in _sessions:
        raise HTTPException(status_code=404, detail="Session not found")

    agent = _sessions[session_id]
    agent.clear_history()
    return {"success": True, "session_id": session_id}


# Tool endpoints (for direct tool access without chat)


@router.post("/tools/roll", response_model=DiceRollResponse)
async def roll_dice(request: DiceRollRequest) -> DiceRollResponse:
    """Roll dice using standard notation.

    Examples:
    - "1d20" - Single d20
    - "2d6+3" - Two d6 plus 3
    - "4d6 drop lowest" - Ability score roll
    """
    try:
        from backend.agents.tools import DMTools

        tools = DMTools()
        result = tools.roll_dice(request.expression)
        return DiceRollResponse(
            expression=result.expression,
            rolls=result.rolls,
            modifier=result.modifier,
            total=result.total,
            critical=result.critical,
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/tools/npc")
async def generate_npc(request: NPCRequest) -> dict:
    """Generate a random NPC."""
    try:
        from backend.agents.tools import DMTools

        tools = DMTools()
        result = tools.generate_npc(role=request.role, race=request.race)
        return result.model_dump()
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/tools/encounter")
async def generate_encounter(request: EncounterRequest) -> dict:
    """Generate a combat encounter."""
    try:
        from backend.agents.tools import DMTools

        tools = DMTools()
        result = tools.generate_encounter(
            difficulty=request.difficulty,
            environment=request.environment,
            party_level=request.party_level,
            party_size=request.party_size,
        )
        return result.model_dump()
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# WebSocket for real-time chat


@router.websocket("/ws/{session_id}")
async def websocket_chat(websocket: WebSocket, session_id: str):
    """WebSocket endpoint for real-time chat.

    Enables streaming responses and real-time interaction.
    """
    await websocket.accept()

    # Get or create session
    _, agent = get_or_create_session(session_id=session_id)

    try:
        while True:
            # Receive message
            data = await websocket.receive_json()
            message = data.get("message", "")

            # Process message
            result = await agent.process_message(
                user_input=message,
            )

            # Send response
            await websocket.send_json({
                "type": "response",
                "message": result.message,
                "query_type": result.query_type.value if result.query_type else None,
                "sources": result.sources,
                "tool_results": result.tool_results,
                "suggestions": result.suggestions,
            })

    except WebSocketDisconnect:
        # Client disconnected - keep session alive for reconnection
        pass
    except Exception as e:
        await websocket.send_json({
            "type": "error",
            "message": str(e),
        })
