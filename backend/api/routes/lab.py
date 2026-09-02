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
from collections import OrderedDict
from typing import Literal, Optional

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field, field_validator

from backend.agents import canon_context, generator
from backend.agents.dm_agent import DMAgent, DMResponse
from backend.canon import books
from backend.canon.retrieval import CanonRetriever
from backend.core import pricing
from backend.core.config import settings

logger = logging.getLogger(__name__)
from backend.api.routes.homebrew import dm_only

#: The assistant reads the whole book, so it cannot be narrowed to what a
#: table has been shown -- and a model given a secret and asked not to say it
#: has already been given the secret.
_ASSISTANT_IS_THE_DMS = (
    "the assistant reads the whole book, so it answers the DM only. What your "
    "table has been shown is on the log and on the entity and scene pages."
)

router = APIRouter()

#: How many conversations one process keeps. Reached only by a deployment with
#: more readers than that holding sessions at once, and the eviction costs the
#: oldest of them their thread -- which is why it is well above a table.
_MAX_SESSIONS = 64

#: Per-process, per-session agents, oldest use first.
#:
#: KEYED BY WHATEVER THE CLIENT CALLS ITS SESSION, and the client used to call
#: it `'lab'` -- every reader of the deployment sharing one history, one
#: person's questions arriving in the next one's context. Each browser now
#: mints its own id, which fixed that and made this dict grow: one agent per
#: reader rather than exactly one, and nothing ever released them.
#:
#: BOUNDED, NOT EXPIRED. A `DMAgent` holds a conversation and a subgraph and
#: nothing about it says when it stopped being wanted; a reader who comes back
#: after lunch should find their thread. So the cap is on COUNT and eviction is
#: least-recently-used, which drops the session nobody has touched in longest
#: rather than guessing at a timeout.
_SESSIONS: OrderedDict[str, DMAgent] = OrderedDict()


async def _placed(client, subject: str, body: str, retrieval, model: str) -> str:
    """The model's read of which beat this comes after, or `""`.

    NEVER FAILS THE GENERATION. The DM has already paid for the card; a
    placement call that errors costs them a better anchor and nothing else, and
    `suggest_anchor`'s answer is still there to fall back on.
    """
    from backend.agents import canon_context

    try:
        return await canon_context.place_it(
            client, subject=subject, body=body,
            shown=canon_context.sources(retrieval), model=model,
        )
    except Exception:  # noqa: BLE001 -- a better anchor is not worth a 500
        logger.exception("could not place the generation in the running order")
        return ""


def _remember(session_id: str, agent: DMAgent) -> DMAgent:
    """Store the agent as most-recently-used, evicting the coldest over the cap."""
    _SESSIONS[session_id] = agent
    _SESSIONS.move_to_end(session_id)
    while len(_SESSIONS) > _MAX_SESSIONS:
        evicted, _ = _SESSIONS.popitem(last=False)
        logger.info("evicted lab session %s (cap %d)", evicted, _MAX_SESSIONS)
    return agent


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
async def chat(http: Request, request: ChatRequest) -> dict:
    """One grounded turn, with its cost and its retrieval laid open.

    THE DM ONLY. Retrieval seeds itself from the whole book, so this is the one
    surface that cannot be narrowed to what a table has been shown -- see
    `homebrew.dm_only` for why it is closed rather than filtered.
    """
    dm_only(http, request.campaign or "", _ASSISTANT_IS_THE_DMS)
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

    _save_memory(agent, request.session_id, request.book, request.campaign)

    return {
        "message": result.message,
        "sources": result.sources,
        "usage": result.usage,
        "cost": result.cost,
        "retrieval": result.retrieval,
        "subgraph": _with_provenance(result.subgraph),
        # AN EXPLICIT ALLOWLIST DROPS WHATEVER IT DOES NOT NAME. The draft
        # cards were generated, cost money, and vanished here -- the model
        # said "a draft is ready for review" and the reader was shown nothing.
        # Anything added to `DMResponse` has to be added here too.
        "generations": result.generations,
        "model": model,
    }


@router.post("/generate")
async def generate(http: Request, request: GenerateRequest) -> dict:
    """A quest, NPC or monster, with canon and invention kept apart."""
    dm_only(http, request.campaign or "", _ASSISTANT_IS_THE_DMS)
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
    #
    # AND THE SAME REFINEMENT, WHICH IT DID NOT GET. The chat card asks
    # `place_it` over the shown passages and kept only the deterministic answer
    # here -- so the same generation, made from the same retrieval, was filed by
    # a better rule in one tab than the other. `suggest_anchor` answers "which
    # section names the subject most", which is right 4 times in 10 on the
    # hand-authored cases, and is wrong in one direction: a scene about getting
    # somewhere files where the party arrives.
    anchor, chapters = canon_context.suggest_anchor(retrieval)
    anchor = await _placed(agent.openai, request.subject,
                           str(result.as_dict().get("body") or ""),
                           retrieval, model) or anchor
    return result.as_dict() | {
        "model": model,
        "anchor": anchor,
        "relevant_chapters": list(chapters),
    }


class FindElementsRequest(BaseModel):
    """A draft the DM wants the cast of."""

    body: str
    subject: str
    #: What the material IS, so the ontology can say which episodes may sit
    #: inside it. Absent is fine: nothing is refused on containment then.
    kind: str = ""
    book: str = "cos"
    campaign: str | None = None
    model: str | None = None
    depth: Depth = Field(default_factory=Depth)


@router.post("/find-elements")
async def find_elements(http: Request, request: FindElementsRequest) -> dict:
    """Ask a draft what things it contains, on demand.

    A QUEST, SCENE OR ENCOUNTER IS ANNOTATED WHEN IT IS WRITTEN, and when that
    pass finds nothing the DM is left with a single entity and no way to ask
    again. It is not a rare outcome: the pass is element-first, so it reads
    prose looking for things to MINT and goes quiet exactly when the scene is
    built out of people who already exist -- which is most of the second scene
    a table writes.

    So the ask becomes a button. Same `annotate` the write path runs, over the
    body as it now stands rather than as it was generated, because the DM has
    usually edited it by the time they notice the cast is missing.

    NOTHING IS WRITTEN. What comes back populates the review the card already
    has, where each element is ticked or unticked before any of it is stored.
    """
    model = request.model or settings.openai_model
    depth = request.depth.to_domain()
    if not request.body.strip():
        return {"elements": [], "edges": [], "dropped": {}}

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
    elements, edges, dropped, error = await generator.annotate(
        agent.openai,
        body=request.body,
        retrieval=retrieval,
        depth=depth,
        model=model,
        subject=request.subject,
        kind=request.kind,
    )
    if error:
        raise HTTPException(status_code=502, detail=f"could not read the cast: {error}")
    return {
        "elements": [dict(e) for e in elements],
        "edges": [dict(x) for x in edges],
        # COUNTED, NEVER SILENT. A kind the graph will not mint is a thing the
        # DM asked for and did not get, and saying so is cheaper than letting
        # them wonder where it went.
        "dropped": dropped,
    }


@router.post("/reset")
def reset(session_id: str = "lab") -> dict:
    """Drop a session's history. The knobs are per-request, so nothing else."""
    _SESSIONS.pop(session_id, None)
    # AND THE STORED COPY. Dropping only the live agent would leave a reset
    # session restoring its old subgraph on the next question -- a Reset button
    # that does not reset.
    from backend.campaign import memory
    from backend.core.database import neo4j_session

    try:
        with neo4j_session() as session:
            session.execute_write(
                lambda tx: memory.forget(tx, session_id=session_id))
    except Exception:  # noqa: BLE001
        logger.exception("could not forget session memory for %s", session_id)
    return {"ok": True, "session_id": session_id}


#: Which of these nodes the book does not name. Read here rather than carried
#: through `subgraph.Held`, because the subgraph is built from anchors and from
#: names an answer used, and NEITHER KNOWS THIS. Threading a field those call
#: sites cannot fill would mean defaulting it, and a default of "the book names
#: this" is the one wrong answer -- it would assert canon over the 154 nodes
#: that have none.
_PROVENANCE = """
MATCH (e:Entity) WHERE e.id IN $ids
RETURN collect(CASE WHEN e.plane = 'canon' THEN e.id END) AS canon,
       collect(CASE WHEN e.named_by_book = false THEN e.id END) AS unnamed
"""


def _with_provenance(subgraph: dict | None) -> dict | None:
    """Mark the subgraph's nodes the book does not name.

    THE PANEL IS WHERE A DM SEES WHAT AN ANSWER WAS BUILT ON, and until now it
    showed a node the extractor invented exactly like one the book prints. The
    entity card had said so since the marking landed; this is the same fact at
    the place the reader actually looks.

    ONLY CANON NODES ARE ANSWERED FOR, which this did not do and its own
    docstring claimed it did. It stamped every node, so a campaign session --
    whose subgraph holds the DM's own invented NPCs -- got `named_by_book: true`
    on them: "the book names this", asserted over an invention, in the one panel
    built to prevent exactly that. A node that is not canon gets no field at
    all, and the frontend renders a badge only on an explicit `false`.

    ABSENT MEANS NOT MARKED, NEVER "unknown", for canon nodes too: a canon id
    the graph cannot find is left alone rather than described either way.
    """
    if not subgraph or not subgraph.get("nodes"):
        return subgraph
    from backend.core.database import read_only_session

    ids = [n["id"] for n in subgraph["nodes"] if n.get("id")]
    try:
        with read_only_session() as session:
            row = session.run(_PROVENANCE, {"ids": ids}).single()
            canon = {i for i in (row["canon"] or []) if i}
            unnamed = {i for i in (row["unnamed"] or []) if i}
    except Exception:  # noqa: BLE001 -- a panel decoration is not worth a 500
        logger.exception("could not read provenance for the subgraph")
        return subgraph
    for node in subgraph["nodes"]:
        if node.get("id") in canon:
            node["named_by_book"] = node["id"] not in unnamed
    return subgraph


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
        # A READ IS A USE. Without this the cap would evict by age of creation
        # and drop the session of whoever has been talking longest.
        _SESSIONS.move_to_end(session_id)
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
    elif existing is None:
        # NOTHING IN THIS PROCESS KNOWS THIS SESSION, which is the case a
        # restart, a deploy and an LRU eviction all look like. The subgraph IS
        # the conversation's memory -- `_trim` bounds the transcript and leans
        # on it -- so without this every deploy was amnesia mid-campaign.
        #
        # ONLY WHEN THERE IS NO LIVE AGENT. A rebuild for a changed knob
        # already carries the subgraph across in the branch above, and reading
        # a stored one over it would put an older working set in front of the
        # DM than the one they have been talking to.
        _restore_memory(rebuilt, session_id, book, campaign)
    return _remember(session_id, rebuilt)


def _save_memory(agent: DMAgent, session_id: str, book: str,
                 campaign: str | None) -> None:
    """Write what the turn left the conversation knowing.

    AFTER THE ANSWER, NEVER BEFORE IT. The DM has already paid for this reply;
    a memory store that is down must not turn a successful turn into a 500, so
    the failure is logged and the session goes on working exactly as it did
    before any of this existed -- in memory, until the process ends.
    """
    from datetime import UTC, datetime

    from backend.campaign import memory
    from backend.core.database import neo4j_session

    try:
        with neo4j_session() as session:
            session.execute_write(lambda tx: memory.save(
                tx, session_id=session_id, book=book, campaign=campaign,
                snapshot=agent.subgraph.snapshot(),
                updated_at=datetime.now(UTC).isoformat(),
            ))
    except Exception:  # noqa: BLE001 -- an answer already given is not worth a 500
        logger.exception("could not save session memory for %s", session_id)


def _restore_memory(agent: DMAgent, session_id: str, book: str,
                    campaign: str | None) -> None:
    """Give a fresh agent whatever the last process knew, if anything.

    NEVER FAILS A QUESTION. A DM asking something should not meet a 500 because
    the memory store is unreachable; they get the fresh session they would have
    had anyway, and the failure is logged rather than raised.
    """
    from backend.agents.subgraph import Subgraph
    from backend.campaign import memory
    from backend.core.database import read_only_session

    try:
        with read_only_session() as session:
            payload = session.execute_read(
                lambda tx: memory.load(
                    tx, session_id=session_id, book=book, campaign=campaign)
            )
    except Exception:  # noqa: BLE001 -- a restored thread is not worth a 500
        logger.exception("could not restore session memory for %s", session_id)
        return
    if payload:
        agent.subgraph = Subgraph.restore(payload)
        logger.info("restored session %s: %d nodes", session_id,
                    len(agent.subgraph.nodes))
