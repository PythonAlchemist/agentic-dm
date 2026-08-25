"""Approve a generation into the graph, or take it back out.

THE CARD IS THE GATE. A generation is held by the client until a person looks
at it and presses store; nothing a model produces reaches the graph on its own.
That is the same rule the alias and edge-review scripts follow -- a model
proposes, a human reads, one step applies -- moved to where a DM works.

THE DRAFT IS NOT SERVER STATE. `/lab/generate` already returns the whole
payload and throws it away; storing is posting that payload back, possibly
edited. A server-side draft would die on restart, and the lab is explicit that
its in-memory sessions are scratch. A store flow that depends on a session
surviving is a store flow that loses work.

VALIDATED AGAIN HERE. The payload has been through a browser and a person's
hands since the model produced it, so the two required provenance lists are
re-checked and every citation is resolved against sections that actually exist.
The schema-level contract is worth nothing if the persistence boundary takes
the client's word for it.
"""

from __future__ import annotations

import logging
from typing import Literal

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from backend.campaign import homebrew, store
from backend.campaign.chain import move_plan, position_for, remove_plan, walk
from backend.core.database import neo4j_session, read_only_session

logger = logging.getLogger(__name__)
router = APIRouter()


class StoreRequest(BaseModel):
    campaign: str
    kind: Literal["quest", "npc", "monster", "scene"]
    title: str
    body: str
    #: What the model wrote before the DM touched it. Kept beside `body` so
    #: "what did a person change" stays answerable.
    generated_body: str = ""
    from_canon: list[dict] = Field(default_factory=list)
    invented: list[str] = Field(default_factory=list)
    from_context: list[str] = Field(default_factory=list)
    sources: list[dict] = Field(default_factory=list)
    #: The canon section this goes after in the running order. None means the
    #: DM did not place it -- legal, and the only option for a campaign with no
    #: book at all.
    anchor: str | None = None
    model: str = ""


class OrderRequest(BaseModel):
    campaign: str
    section_id: str
    #: For a move. None puts it at the head.
    after: str | None = None


@router.get("/campaigns")
def campaigns() -> dict:
    """Every campaign, with what it draws on and how long its order is."""
    try:
        with read_only_session() as session:
            found = store.read_campaigns(session)
            return {
                "campaigns": [
                    {
                        "slug": c.slug,
                        "name": c.name,
                        "books": list(c.books),
                        "sections": len(store.running_order(session, c.slug)),
                    }
                    for c in found
                ]
            }
    except Exception:  # noqa: BLE001 - a picker is not worth failing a page for
        logger.warning("could not list campaigns", exc_info=True)
        return {"campaigns": []}


@router.get("/running-order")
def running_order(campaign: str) -> dict:
    """What this table plays, in order, with each section's origin.

    SKIPPED SECTIONS ARE RETURNED IN PLACE, marked. A section the DM cut that
    simply vanished from the list would read as one that never existed, and the
    DM would have no way to put it back.
    """
    with read_only_session() as session:
        links, start = store.read_chain(session, campaign)
        order = list(walk(links, start, bound=len(links) + 2).order)
        skipped = store.read_skipped(session, campaign)
        found = {c.slug: c for c in store.read_campaigns(session)}
        campaign_row = found.get(campaign)
        spine = (
            [s for b in campaign_row.books for s in store.spine_order(session, b)]
            if campaign_row
            else []
        )
        headings = {
            dict(r)["id"]: dict(r)["heading"]
            for r in session.run(
                "MATCH (s:Section) WHERE s.id IN $ids RETURN s.id AS id, s.heading AS heading",
                {"ids": order + sorted(skipped)},
            )
        }

    placed = {section_id: index for index, section_id in enumerate(order)}
    rows = [
        {
            "section_id": section_id,
            "heading": headings.get(section_id, section_id),
            "origin": "campaign" if section_id.startswith("hb:") else "canon",
            "skipped": False,
        }
        for section_id in order
    ]
    # Skipped sections are slotted back at the book position they would occupy,
    # so the list reads as the book with cuts marked rather than as a book with
    # holes in it.
    for section_id in sorted(skipped, key=lambda s: spine.index(s) if s in spine else 0):
        after = position_for(spine, frozenset(placed), section_id)
        at = placed.get(after, -1) + 1 if after else 0
        rows.insert(
            at,
            {
                "section_id": section_id,
                "heading": headings.get(section_id, section_id),
                "origin": "canon",
                "skipped": True,
            },
        )
    return {"campaign": campaign, "sections": rows}


@router.post("/store")
def store_generation(request: StoreRequest) -> dict:
    """Write an approved generation. One transaction, or nothing."""
    if not request.from_canon and not request.invented:
        raise HTTPException(
            status_code=400,
            detail=(
                "a generation with neither a canon list nor an invented list has "
                "no provenance at all; nothing was stored"
            ),
        )

    with read_only_session() as session:
        known = {c.slug for c in store.read_campaigns(session)}
        if request.campaign not in known:
            raise HTTPException(status_code=404, detail=f"no campaign {request.campaign!r}")
        if request.anchor:
            found = session.run(
                "MATCH (s:Section {id:$id, plane:'canon'}) RETURN count(s) AS c",
                {"id": request.anchor},
            ).single()["c"]
            if not found:
                raise HTTPException(
                    status_code=400,
                    detail=f"anchor {request.anchor!r} is not a canon section",
                )

    _resolved, bad = homebrew.cited_sections(request.from_canon, request.sources)
    if bad:
        raise HTTPException(
            status_code=400,
            detail=(
                f"{len(bad)} citation(s) point at nothing that was shown: {bad[:3]}. "
                "A citation that resolves to no passage is a number, not a pointer."
            ),
        )

    try:
        with neo4j_session() as session:
            stored = session.execute_write(
                lambda tx: homebrew.write(
                    tx,
                    slug=request.campaign,
                    kind=request.kind,
                    title=request.title,
                    body=request.body,
                    generated_body=request.generated_body or request.body,
                    from_canon=request.from_canon,
                    invented=request.invented,
                    from_context=request.from_context,
                    sources=request.sources,
                    anchor=request.anchor,
                    model=request.model,
                )
            )
    except homebrew.AlreadyStored as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except store.ChainCorrupted as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except Exception as exc:  # noqa: BLE001 - surfaced, not swallowed
        logger.exception("storing homebrew failed")
        raise HTTPException(status_code=500, detail=str(exc)) from exc

    return stored.as_dict()


@router.delete("/store")
def delete_generation(campaign: str, entity_id: str) -> dict:
    """Remove a stored generation, splicing the running order shut."""
    with neo4j_session() as session:
        return session.execute_write(
            lambda tx: homebrew.delete(tx, slug=campaign, entity_id=entity_id)
        )


@router.post("/skip")
def skip(request: OrderRequest) -> dict:
    """Cut a section from the running order, RECORDING that it was cut."""
    with neo4j_session() as session:
        def run(tx):
            links, start = store.read_chain(tx, request.campaign)
            in_chain = frozenset(walk(links, start, bound=len(links) + 2).order)
            if request.section_id not in in_chain:
                return {"changed": 0, "noop": "already out of the running order"}
            plan = remove_plan(links, start, request.section_id)
            result = store.apply_rewire(
                tx, request.campaign, plan, in_chain - {request.section_id}
            )
            store.mark_skipped(tx, request.campaign, request.section_id)
            return result

        return session.execute_write(run)


@router.post("/unskip")
def unskip(request: OrderRequest) -> dict:
    """Put a cut section back at its BOOK position, not at the end.

    The same rule reconciliation uses, deliberately: a section the DM has
    expressed no opinion about where to put goes where the book puts it.
    """
    with read_only_session() as session:
        found = {c.slug: c for c in store.read_campaigns(session)}
        campaign = found.get(request.campaign)
        spine = (
            [s for b in campaign.books for s in store.spine_order(session, b)]
            if campaign
            else []
        )

    with neo4j_session() as session:
        def run(tx):
            links, start = store.read_chain(tx, request.campaign)
            in_chain = frozenset(walk(links, start, bound=len(links) + 2).order)
            after = position_for(spine, in_chain, request.section_id)
            from backend.campaign.chain import insert_plan

            plan = insert_plan(links, start, request.section_id, after)
            result = store.apply_rewire(
                tx, request.campaign, plan, in_chain | {request.section_id}
            )
            store.clear_skipped(tx, request.campaign, request.section_id)
            return result

        return session.execute_write(run)


@router.post("/move")
def move(request: OrderRequest) -> dict:
    """Put a section somewhere else in the running order."""
    with neo4j_session() as session:
        def run(tx):
            links, start = store.read_chain(tx, request.campaign)
            in_chain = frozenset(walk(links, start, bound=len(links) + 2).order)
            plan = move_plan(links, start, request.section_id, request.after)
            if plan.noop:
                return {"changed": 0, "noop": plan.noop}
            return store.apply_rewire(tx, request.campaign, plan, in_chain)

        try:
            return session.execute_write(run)
        except store.ChainCorrupted as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
