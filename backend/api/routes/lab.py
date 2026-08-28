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
from pydantic import BaseModel, Field, field_validator

from backend.agents import canon_context, generator
from backend.agents.dm_agent import DMAgent, DMResponse
from backend.canon import books
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
    passage_width: Literal["sentence", "section"] = "section"

    def to_domain(self) -> canon_context.Depth:
        return canon_context.Depth(
            passages=self.passages,
            max_edges=self.max_edges,
            include_proposed=self.include_proposed,
            passage_width=self.passage_width,
        )


class ChatRequest(BaseModel):
    message: str
    session_id: str = "lab"
    model: Optional[str] = None
    #: Which book this session is running. A session reads ONE, the way a table
    #: runs one adventure -- see `CanonRetriever`.
    book: str = "cos"
    #: The campaign whose material rides alongside canon. None is the DEFAULT
    #: and means canon only -- the same default the evaluation harnesses use.
    campaign: str | None = None
    depth: Depth = Field(default_factory=Depth)
    #: WHAT THE DM HAS OPEN: a section id or an entity id, or empty.
    #:
    #: A PRIOR, NOT A FILTER. Retrieval still reads the whole graph; this only
    #: fills anchor slots the question itself did not, so nothing typed can be
    #: outvoted by what happens to be on screen. Passages that arrive this way
    #: are labelled `focus`, because a bias nobody can see is indistinguishable
    #: from the tool quietly getting worse.
    focus: str = ""
    #: Off by default. The campaign RAG pipeline needs a populated vector store
    #: and answers about the campaign plane; this lab is about canon.


class GenerateRequest(BaseModel):
    """A cold ask. `kind` is checked against the generator's own `KINDS`,
    which is what a DM may request outright -- narrower than what `expand`
    accepts, because a location or a piece of lore is minted by a cluster and
    then fleshed out, never asked for bare."""

    kind: str  # validated against `generator.KINDS`, never repeated here
    subject: str
    book: str = "cos"
    campaign: str | None = None
    model: Optional[str] = None
    depth: Depth = Field(default_factory=Depth)
    #: The draft being replaced, and the one thing to change about it. Both or
    #: neither: a note with no draft is just a longer subject, and a draft with
    #: no note asks for the same thing twice. The retrieval is re-run on the
    #: same subject, so a revision cites the same passages the first attempt
    #: did rather than drifting onto different evidence.
    previous: str = ""
    note: str = ""

    @field_validator("kind")
    @classmethod
    def _askable(cls, value: str) -> str:
        if value not in generator.KINDS:
            raise ValueError(
                f"unknown kind {value!r}; expected one of {sorted(generator.KINDS)}"
            )
        return value


@router.get("/config")
def config() -> dict:
    """Models on offer, their rates, how old those rates are, and what is loaded.

    `books` is COUNTED, never written down -- both which books are here and how
    much of each. The lab header read "3 of 25 chapters loaded" long after the
    whole book was in the graph, and the model's own no-canon instruction
    carried the same stale sentence: a number describing the state of a
    database does not belong in a string somebody has to remember to update.
    The book TITLES come from the graph for the same reason, now that there is
    more than one and the header used to name Curse of Strahd unconditionally.
    """
    return {
        "models": pricing.models(),
        "default_model": settings.openai_model,
        "kinds": list(generator.KINDS),
        "defaults": Depth().model_dump(),
        "books": _books_loaded(),
    }


def _books_loaded() -> list[dict]:
    """Every book in the graph, with its title and how much of it is here.

    COUNTED, for the reason `config` gives: a list of books written into a
    constant goes stale the first time somebody loads one, and this lab has
    already shipped one stale count.
    """
    from backend.core.database import read_only_session

    try:
        with read_only_session() as session:
            rows = [
                dict(record)
                for record in session.run(
                    """
                    MATCH (b:Book {plane:'canon'})
                    OPTIONAL MATCH (b)-[:HAS_CHAPTER]->(c:Chapter)
                    RETURN b.slug AS slug, b.display_name AS title,
                           count(c) AS chapters
                    ORDER BY chapters DESC
                    """
                )
            ]
    except Exception:  # noqa: BLE001 - a picker is not worth failing a page for
        logger.warning("could not list loaded books", exc_info=True)
        return []

    # The starter subjects come from each book's OWN seed, so a lab showing
    # Keys from the Golden Vault stops offering a Barovia tavern. A book whose
    # seed is missing or names none simply offers none.
    for row in rows:
        seed = books.SEEDS / f"{row['slug']}.yaml"
        try:
            row["examples"] = books.load(seed).examples if seed.exists() else {}
        except Exception:  # noqa: BLE001
            logger.warning("could not read examples for %s", row["slug"], exc_info=True)
            row["examples"] = {}
    return rows


@router.post("/chat")
async def chat(request: ChatRequest) -> dict:
    """One grounded turn, with its cost and its retrieval laid open."""
    model = request.model or settings.openai_model
    depth = request.depth.to_domain()
    agent = _agent_for(request.session_id, model, depth, request.book, request.campaign)
    # SET PER TURN, not per session. The DM clicks through from a scene to
    # somebody in it while the conversation carries on, and the focus has to
    # follow them -- a session-lifetime value would go stale the moment they
    # moved, which is the failure mode this design was warned about.
    agent.focus = request.focus

    try:
        result: DMResponse = await agent.process_message(
            user_input=request.message,
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
        "subgraph": result.subgraph,
        # AN EXPLICIT ALLOWLIST DROPS WHATEVER IT DOES NOT NAME. The draft
        # cards were generated, cost money, and vanished here -- the model
        # said "a draft is ready for review" and the reader was shown nothing.
        # Anything added to `DMResponse` has to be added here too.
        "generations": result.generations,
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
    agent = DMAgent(
        model=model,
        depth=depth,
        canon=CanonRetriever(
            limit=depth.passages,
            passage_width=depth.passage_width,
            book=request.book,
            campaign=request.campaign,
        ),
    )
    retrieval = agent._retrieve_canon(request.subject)

    try:
        result = await generator.generate(
            agent.openai,
            kind=request.kind,
            subject=request.subject,
            retrieval=retrieval,
            depth=depth,
            model=model,
            previous=request.previous,
            note=request.note,
        )
    except Exception as exc:  # noqa: BLE001
        logger.exception("lab generate failed")
        raise HTTPException(status_code=500, detail=str(exc)) from exc

    # The Generate tab gets the same suggestion the chat card does: one
    # generator, two callers, neither left guessing where a scene belongs.
    anchor, chapters = canon_context.suggest_anchor(retrieval)
    return result.as_dict() | {
        "model": model,
        "anchor": anchor,
        "relevant_chapters": list(chapters),
    }


@router.post("/reset")
def reset(session_id: str = "lab") -> dict:
    """Drop a session's history. The knobs are per-request, so nothing else."""
    _SESSIONS.pop(session_id, None)
    return {"ok": True, "session_id": session_id}


def _agent_for(
    session_id: str,
    model: str,
    depth: canon_context.Depth,
    book: str = "cos",
    campaign: str | None = None,
) -> DMAgent:
    """The session's agent, rebuilt when a knob it was built with has changed.

    Model and passage count are fixed at construction -- the retriever carries
    the limit -- so a changed knob needs a new agent. The CONVERSATION AND THE
    SUBGRAPH are carried across, because losing the thread every time somebody
    switches model would defeat the one comparison this lab is for: same
    conversation, different model.

    The subgraph especially, now that the transcript is bounded to the current
    question: it IS the memory, so a rebuilt agent that dropped it would forget
    who the conversation was about the moment a slider moved.
    """
    existing = _SESSIONS.get(session_id)
    # A CAMPAIGN CHANGE IS A WORLD CHANGE, exactly as a book change is: the
    # subgraph holds entities by id, and carrying a table's own scenes into
    # another table's session is the same bleed, one scope in.
    same_book = existing is not None and (
        existing.canon.book == book and existing.canon.campaign == campaign
    )
    if existing is not None and same_book and existing.model == model and existing.depth == depth:
        return existing

    rebuilt = DMAgent(
        model=model,
        depth=depth,
        canon=CanonRetriever(
            limit=depth.passages,
            passage_width=depth.passage_width,
            book=book,
            campaign=campaign,
        ),
    )
    # CHANGING BOOK STARTS A NEW THREAD, unlike changing model. The subgraph
    # holds entities by id, so carrying it into another book would put Barovia
    # in front of a heist -- the cross-book bleed that scoping the retriever
    # exists to stop, re-entering through the conversation's own memory.
    if existing is not None and same_book:
        rebuilt.conversation = existing.conversation
        rebuilt.subgraph = existing.subgraph
    _SESSIONS[session_id] = rebuilt
    return rebuilt
