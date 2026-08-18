"""The agent lab: one agent, exposed knobs, and what every call cost.

Separate from `/api/chat` on purpose. That route serves the application, where
model and context depth are settings somebody chose once. This one exists to
CHANGE them and watch what happens, so every knob is a request field and every
response carries what the call consumed and what retrieval actually found.

Sessions are held in memory, per process. A lab session is a few minutes of
comparison, not something to persist -- and a restart clearing them is the
honest behaviour for a tool whose whole purpose is trying settings out.
"""

from __future__ import annotations

import logging
from typing import Literal, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from backend.agents import canon_context, generator
from backend.agents.dm_agent import DMAgent, DMResponse
from backend.canon.retrieval import CanonRetriever
from backend.core import pricing
from backend.core.config import settings

logger = logging.getLogger(__name__)
router = APIRouter()

#: Per-process, per-session agents. Keyed by whatever the client calls its
#: session; the client owns that string and a collision only ever costs a
#: shared history in a scratch tool.
_SESSIONS: dict[str, DMAgent] = {}


class Depth(BaseModel):
    """The context knobs, mirroring `canon_context.Depth`.

    Bounded here rather than trusted. `passages` especially: retrieval will
    happily return every section mentioning Strahd, and an unbounded value from
    a browser is a way to spend real money by typing a big number.
    """

    passages: int = Field(default=canon_context.Depth.passages, ge=0, le=20)
    max_edges: int = Field(default=12, ge=0, le=50)
    include_proposed: bool = True
    history_turns: int = Field(default=6, ge=0, le=20)
    passage_width: Literal["sentence", "section"] = "section"

    def to_domain(self) -> canon_context.Depth:
        return canon_context.Depth(
            passages=self.passages,
            max_edges=self.max_edges,
            include_proposed=self.include_proposed,
            history_turns=self.history_turns,
            passage_width=self.passage_width,
        )


class ChatRequest(BaseModel):
    message: str
    session_id: str = "lab"
    model: Optional[str] = None
    depth: Depth = Field(default_factory=Depth)
    #: Off by default. The campaign RAG pipeline needs a populated vector store
    #: and answers about the campaign plane; this lab is about canon.
    use_rag: bool = False


class GenerateRequest(BaseModel):
    kind: Literal["quest", "npc", "monster"]
    subject: str
    model: Optional[str] = None
    depth: Depth = Field(default_factory=Depth)


@router.get("/config")
def config() -> dict:
    """Models on offer, their rates, and how old those rates are."""
    return {
        "models": pricing.models(),
        "default_model": settings.openai_model,
        "kinds": list(generator.KINDS),
        "defaults": Depth().model_dump(),
    }


@router.post("/chat")
async def chat(request: ChatRequest) -> dict:
    """One grounded turn, with its cost and its retrieval laid open."""
    model = request.model or settings.openai_model
    depth = request.depth.to_domain()
    agent = _agent_for(request.session_id, model, depth)

    try:
        result: DMResponse = await agent.process_message(
            user_input=request.message,
            use_rag=request.use_rag,
            use_canon=True,
        )
    except Exception as exc:  # noqa: BLE001 - surfaced to the lab, not swallowed
        logger.exception("lab chat failed")
        raise HTTPException(status_code=500, detail=str(exc)) from exc

    return {
        "message": result.message,
        "sources": result.sources,
        "usage": result.usage,
        "cost": result.cost,
        "retrieval": result.retrieval,
        "model": model,
    }


@router.post("/generate")
async def generate(request: GenerateRequest) -> dict:
    """A quest, NPC or monster, with canon and invention kept apart."""
    model = request.model or settings.openai_model
    depth = request.depth.to_domain()

    # A FRESH agent every time, and never a session one. Generation has no
    # conversation: reusing a chat session's agent would quietly feed it
    # whatever was discussed before and make two identical requests return
    # different things for reasons nobody could see.
    agent = DMAgent(model=model, depth=depth)
    retrieval = agent._retrieve_canon(request.subject)

    try:
        result = await generator.generate(
            agent.openai,
            kind=request.kind,
            subject=request.subject,
            retrieval=retrieval,
            depth=depth,
            model=model,
        )
    except Exception as exc:  # noqa: BLE001
        logger.exception("lab generate failed")
        raise HTTPException(status_code=500, detail=str(exc)) from exc

    return result.as_dict() | {"model": model}


@router.post("/reset")
def reset(session_id: str = "lab") -> dict:
    """Drop a session's history. The knobs are per-request, so nothing else."""
    _SESSIONS.pop(session_id, None)
    return {"ok": True, "session_id": session_id}


def _agent_for(session_id: str, model: str, depth: canon_context.Depth) -> DMAgent:
    """The session's agent, rebuilt when a knob it was built with has changed.

    Model and passage count are fixed at construction -- the retriever carries
    the limit -- so a changed knob needs a new agent. The CONVERSATION is
    carried across, because losing the thread every time somebody switches model
    would defeat the one comparison this lab is for: same conversation, different
    model.
    """
    existing = _SESSIONS.get(session_id)
    if existing is not None and existing.model == model and existing.depth == depth:
        return existing

    rebuilt = DMAgent(
        model=model,
        depth=depth,
        canon=CanonRetriever(limit=depth.passages, passage_width=depth.passage_width),
    )
    if existing is not None:
        rebuilt.conversation = existing.conversation
    _SESSIONS[session_id] = rebuilt
    return rebuilt
