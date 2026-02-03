"""Chat endpoint for DM Assistant interactions."""

from typing import Optional
from uuid import uuid4

from fastapi import APIRouter, HTTPException, WebSocket, WebSocketDisconnect
from pydantic import BaseModel, Field

from backend.agents import DMAgent, DMMode, DMResponse

router = APIRouter()

# Session storage (in production, use Redis or similar)
_sessions: dict[str, DMAgent] = {}


def get_or_create_session(
    session_id: Optional[str] = None,
    mode: str = "assistant",
    campaign_id: Optional[str] = None,
) -> tuple[str, DMAgent]:
    """Get existing session or create new one.

    Args:
        session_id: Optional existing session ID.
        mode: DM mode (assistant or autonomous).
        campaign_id: Optional campaign ID.

    Returns:
        Tuple of (session_id, DMAgent).
    """
    if session_id and session_id in _sessions:
        return session_id, _sessions[session_id]

    # Create new session
    new_id = session_id or str(uuid4())
    dm_mode = DMMode.AUTONOMOUS if mode == "autonomous" else DMMode.ASSISTANT
    agent = DMAgent(mode=dm_mode, campaign_id=campaign_id)
    _sessions[new_id] = agent

    return new_id, agent


class ChatMessage(BaseModel):
    """A single chat message."""

    role: str  # "user" or "assistant"
    content: str


class ChatRequest(BaseModel):
    """Chat request payload."""

    message: str
    session_id: Optional[str] = None
    mode: str = "assistant"  # "assistant" or "autonomous"
    campaign_id: Optional[str] = None
    use_rag: bool = True


class ChatResponse(BaseModel):
    """Chat response payload."""

    response: str
    session_id: str
    query_type: Optional[str] = None
    sources: list[dict] = Field(default_factory=list)
    tool_results: list[dict] = Field(default_factory=list)
    suggestions: list[str] = Field(default_factory=list)
    mode: str


class SessionInfo(BaseModel):
    """Session information."""

    session_id: str
    mode: str
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
    - Two modes: assistant (helps DM) and autonomous (runs the game)
    - Tool commands (dice rolling, NPC/encounter generation)
    - RAG-powered context retrieval
    """
    try:
        session_id, agent = get_or_create_session(
            session_id=request.session_id,
            mode=request.mode,
            campaign_id=request.campaign_id,
        )

        # Process the message
        result: DMResponse = await agent.process_message(
            user_input=request.message,
            use_rag=request.use_rag,
        )

        return ChatResponse(
            response=result.message,
            session_id=session_id,
            query_type=result.query_type.value if result.query_type else None,
            sources=result.sources,
            tool_results=result.tool_results,
            suggestions=result.suggestions,
            mode=request.mode,
        )

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/simple")
async def simple_chat(message: str, mode: str = "assistant") -> dict:
    """Simple chat endpoint for quick testing.

    Creates a temporary session for single-turn interactions.
    """
    try:
        agent = DMAgent(
            mode=DMMode.AUTONOMOUS if mode == "autonomous" else DMMode.ASSISTANT
        )
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
        mode=agent.mode.value,
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


@router.post("/sessions/{session_id}/mode")
async def change_session_mode(session_id: str, mode: str) -> SessionInfo:
    """Change the mode of a session."""
    if session_id not in _sessions:
        raise HTTPException(status_code=404, detail="Session not found")

    if mode not in ("assistant", "autonomous"):
        raise HTTPException(status_code=400, detail="Invalid mode")

    agent = _sessions[session_id]
    agent.set_mode(DMMode.AUTONOMOUS if mode == "autonomous" else DMMode.ASSISTANT)

    return SessionInfo(
        session_id=session_id,
        mode=agent.mode.value,
        message_count=len(agent.conversation.messages),
        campaign_id=agent.campaign_id,
    )


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
            use_rag = data.get("use_rag", True)

            # Process message
            result = await agent.process_message(
                user_input=message,
                use_rag=use_rag,
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
