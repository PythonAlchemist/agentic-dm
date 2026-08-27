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

import json
import logging

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field, field_validator

from backend.agents.generator import KINDS, SHAPES
from backend.campaign import homebrew, ontology, store
from backend.campaign.chain import move_plan, position_for, remove_plan, walk
from backend.campaign.model import PART_OF
from backend.core.config import settings
from backend.core.database import neo4j_session, read_only_session

logger = logging.getLogger(__name__)
router = APIRouter()


class StoreRequest(BaseModel):
    campaign: str
    #: VALIDATED AGAINST THE GENERATOR'S OWN SET, never a literal repeated
    #: here. This was `Literal["quest", "npc", "monster", "scene"]` in three
    #: separate files while `KINDS` was the source of truth in a fourth -- and
    #: it bit exactly where predicted: fleshing out a `location` was rejected
    #: by a schema that had never heard of element kinds.
    kind: str
    title: str
    body: str
    #: What the model wrote before the DM touched it. Kept beside `body` so
    #: "what did a person change" stays answerable.
    generated_body: str = ""
    from_canon: list[dict] = Field(default_factory=list)
    #: Claims the card already re-filed as citing the DM's own material. Sent
    #: back so the write can UNION it with `from_canon` and split the pair
    #: again -- the card's honesty must not cost these claims their place, and
    #: the boundary still gets to disbelieve either list.
    from_yours: list[dict] = Field(default_factory=list)
    invented: list[str] = Field(default_factory=list)
    from_context: list[str] = Field(default_factory=list)
    sources: list[dict] = Field(default_factory=list)
    #: The canon section this goes after in the running order. None means the
    #: DM did not place it -- legal, and the only option for a campaign with no
    #: book at all.
    anchor: str | None = None
    model: str = ""

    @field_validator("kind")
    @classmethod
    def _askable(cls, value: str) -> str:
        if value not in KINDS:
            raise ValueError(f"unknown kind {value!r}; expected one of {sorted(KINDS)}")
        return value


class ClusterRequest(StoreRequest):
    """A generation that declares what it contains.

    Extends `StoreRequest` rather than replacing it, so the single-artifact
    path and its tests are untouched and the two cannot drift apart on the
    fields they share.
    """

    elements: list[dict] = Field(default_factory=list)
    edges: list[dict] = Field(default_factory=list)
    #: Element names the DM kept. None means all of them, which is what a
    #: freshly generated card sends before anyone has touched it.
    approved: list[str] | None = None
    #: Keys of backwards edges the DM said to turn round, from
    #: `cluster.edge_key`. Empty by default: a reversed edge is a real
    #: relationship pointing the wrong way, and which way it should point is
    #: not something to decide on the DM's behalf.
    accept_reversed: list[str] = Field(default_factory=list)
    #: Colliding name -> `link` or `rename`.
    resolutions: dict[str, str] = Field(default_factory=dict)


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
        # The chapter travels with the heading so a picker can group by
        # adventure. An anthology's running order is thirteen unconnected
        # heists in a row, and a flat list of 546 sections offers a museum
        # room as readily as the voyage a scene is actually about.
        # THE NESTING TRAVELS TOO. The harvest recorded `depth` and
        # `parent_index` on every canon section and the running order threw
        # both away, so a tree arrived as one flat list -- which is why an
        # encounter that happens DURING a scene could only be placed as its
        # sibling, before the thing it occurs inside.
        found = {
            dict(r)["id"]: dict(r)
            for r in session.run(
                f"""
                MATCH (s:Section) WHERE s.id IN $ids
                OPTIONAL MATCH (c:Chapter)-[:HAS_SECTION]->(s)
                OPTIONAL MATCH (s)-[:{PART_OF}]->(inside:Section)
                RETURN s.id AS id, s.heading AS heading, c.slug AS chapter,
                       s.depth AS depth, s.index AS index,
                       s.parent_index AS parent_index,
                       s.kind AS kind, inside.id AS inside
                """,
                {"ids": order + sorted(skipped)},
            )
        }
        headings = {k: v["heading"] for k, v in found.items()}
        chapters = {k: v["chapter"] for k, v in found.items()}
        # A canon section names its parent by INDEX within its chapter; a
        # campaign one by an edge, because it may sit inside another campaign
        # section and has no index of its own.
        # Keyed on a section's OWN index, which is what `parent_index` points
        # at. Keying it on `parent_index` made every section its own sibling's
        # child: `Trek to the Prison` came back inside `Using the Golden
        # Vault` rather than inside the chapter.
        by_index = {
            (v["chapter"], v["index"]): k
            for k, v in found.items()
            if v["chapter"] is not None
        }
        parents = {
            k: (
                v["inside"]
                or by_index.get((v["chapter"], v["parent_index"]), "")
            )
            for k, v in found.items()
        }
        levels = {
            k: ontology.level_of(v["kind"] or "", v["depth"]) for k, v in found.items()
        }

    placed = {section_id: index for index, section_id in enumerate(order)}
    rows = [
        {
            "section_id": section_id,
            "heading": headings.get(section_id, section_id),
            "origin": "campaign" if section_id.startswith("hb:") else "canon",
            "skipped": False,
            "chapter": chapters.get(section_id) or "",
            "parent": parents.get(section_id) or "",
            "level": levels.get(section_id, "section"),
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
                "chapter": chapters.get(section_id) or "",
                "parent": parents.get(section_id) or "",
                "level": levels.get(section_id, "section"),
            },
        )
    return {"campaign": campaign, "sections": rows}


def _plan_for(request: ClusterRequest):
    """Re-derive the plan from the payload and the graph. Never the client's.

    THE BROWSER'S WORD IS WORTH NOTHING, which is the same rule
    `store_generation` already follows for citations. A payload has been round
    tripped through a page and edited by a person since the model produced it,
    so the collision scan, the id minting and every drop are recomputed here
    rather than trusted.
    """
    from backend.campaign import cluster as cluster_module
    from backend.campaign.cluster import plan_cluster
    from backend.campaign.homebrew import LABELS

    with read_only_session() as session:
        found = {c.slug: c for c in store.read_campaigns(session)}
        campaign = found.get(request.campaign)
        if campaign is None:
            raise HTTPException(status_code=404, detail=f"no campaign {request.campaign!r}")
        aliases = store.canon_aliases(session, campaign.books)
        rows = [
            dict(r)
            for r in session.run(
                "MATCH (e:Entity {plane:'campaign', campaign:$c}) "
                "RETURN e.id AS id, e.kind AS kind",
                {"c": request.campaign},
            )
        ]
        existing = frozenset(r["id"] for r in rows)
        existing_kinds = {
            r["id"]: LABELS.get(r["kind"] or "", "LORE") for r in rows
        }
    # WHAT THE CAMPAIGN ALREADY HOLDS, AND WHAT EACH OF THEM IS. `plan_cluster`
    # stays pure; the types it needs for a reused endpoint are read here and
    # handed over, the same way `canon_aliases` and `existing_ids` are.
    cluster_module._REUSED_KINDS.update(existing_kinds)
    return plan_cluster(
        campaign=request.campaign,
        elements=request.elements,
        edges=request.edges,
        # The generation itself is a node, and the one most declared edges
        # point at.
        root_name=request.title,
        root_kind=request.kind,
        accept_reversed=frozenset(request.accept_reversed or ()),
        canon_aliases=aliases,
        approved=None if request.approved is None else frozenset(request.approved),
        existing_ids=existing,
        resolutions=request.resolutions,
    )


@router.post("/plan-cluster")
def plan_cluster_route(request: ClusterRequest) -> dict:
    """What storing this WOULD do. Writes nothing.

    The card calls this on every edit -- a rename, a rejection, a collision
    resolved -- which is why `plan_cluster` is pure and why this reads rather
    than writes. It is the dry run, and `/store-cluster` is the apply.
    """
    return _plan_for(request).as_dict()


@router.post("/store-cluster")
def store_cluster(request: ClusterRequest) -> dict:
    """Write an approved cluster. One transaction, or nothing."""
    plan = _plan_for(request)
    if not plan.storable:
        raise HTTPException(
            status_code=409,
            detail={
                "message": (
                    f"{len(plan.collisions)} name(s) already exist in this "
                    "campaign's book. Choose what each one means before storing."
                ),
                "collisions": plan.as_dict()["collisions"],
            },
        )

    _resolved, bad = homebrew.cited_sections(
        [*request.from_canon, *request.from_yours], request.sources
    )
    if bad:
        raise HTTPException(
            status_code=400,
            detail=f"{len(bad)} citation(s) point at nothing that was shown: {bad[:3]}",
        )
    if request.anchor:
        with read_only_session() as session:
            found = session.run(
                "MATCH (s:Section {id:$id, plane:'canon'}) RETURN count(s) AS c",
                {"id": request.anchor},
            ).single()["c"]
        if not found:
            raise HTTPException(
                status_code=400, detail=f"anchor {request.anchor!r} is not a canon section"
            )

    try:
        with neo4j_session() as session:
            return session.execute_write(
                lambda tx: homebrew.write_cluster(
                    tx,
                    plan=plan,
                    kind=request.kind,
                    title=request.title,
                    body=request.body,
                    generated_body=request.generated_body or request.body,
                    from_canon=request.from_canon,
                    from_yours=request.from_yours,
                    invented=request.invented,
                    from_context=request.from_context,
                    sources=request.sources,
                    manifest={"elements": request.elements, "edges": request.edges},
                    anchor=request.anchor,
                    model=request.model,
                )
            )
    except homebrew.AlreadyStored as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except store.ChainCorrupted as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except Exception as exc:  # noqa: BLE001
        logger.exception("storing a cluster failed")
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.delete("/store-cluster")
def delete_cluster_route(campaign: str, entity_id: str, cascade: bool = False) -> dict:
    """Remove a cluster, refusing by default while its elements would orphan."""
    try:
        with neo4j_session() as session:
            return session.execute_write(
                lambda tx: homebrew.delete_cluster(
                    tx, slug=campaign, entity_id=entity_id, cascade=cascade
                )
            )
    except homebrew.ClusterHasElements as exc:
        raise HTTPException(
            status_code=409,
            detail={"message": str(exc), "elements": list(exc.members)},
        ) from exc


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

    _resolved, bad = homebrew.cited_sections(
        [*request.from_canon, *request.from_yours], request.sources
    )
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
                    from_yours=request.from_yours,
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


class ExpandRequest(StoreRequest):
    """Prose for something the campaign already holds.

    `title` is ignored -- the entity's own name is authoritative, and letting a
    payload rename a thing while describing it is how two names for one node
    start.
    """

    entity_id: str

    @field_validator("kind")
    @classmethod
    def _askable(cls, value: str) -> str:
        # OVERRIDES the parent's validator by carrying the SAME NAME. Pydantic
        # collects validators across the MRO, so a differently named one here
        # would run BESIDE the parent's rather than instead of it -- and the
        # narrower rule would still reject a location.
        #
        # Wider than `StoreRequest`, deliberately. `KINDS` is what a DM may ask
        # for cold; a cluster also mints locations, items and lore, and every
        # one of those is a thing to flesh out. `SHAPES` is exactly the set the
        # generator has a prompt for.
        if value not in SHAPES:
            raise ValueError(
                f"unknown kind {value!r}; expected one of {sorted(SHAPES)}"
            )
        return value


@router.get("/elements")
def elements(campaign: str, unwritten: bool = False) -> dict:
    """What this campaign has made, and which of it is still a stub.

    THE FRESH-SESSION ENTRY POINT. A conversation started tomorrow holds no
    subgraph and no history; this is how a DM finds what they built and picks
    something up. `unwritten` narrows it to the things with no prose of their
    own, which is the useful question after a cluster lands: a scene mints four
    stubs and the DM flesh them out one at a time over several sittings.
    """
    with read_only_session() as session:
        rows = [
            dict(r)
            for r in session.run(
                """
                MATCH (e:Entity {plane:'campaign', campaign:$c})
                OPTIONAL MATCH (s:Section {expands:e.id})
                OPTIONAL MATCH (root:Section {id:e.cluster})
                RETURN e.id AS entity_id, e.name AS name, e.kind AS kind,
                       e.role AS role, root.heading AS introduced_in,
                       s.id AS own_section
                ORDER BY e.name
                """,
                {"c": campaign},
            )
        ]
    if unwritten:
        rows = [r for r in rows if not r["own_section"]]
    return {
        "campaign": campaign,
        "elements": rows,
        "unwritten": sum(1 for r in rows if not r["own_section"]),
    }


class DraftRequest(BaseModel):
    campaign: str
    entity_id: str
    model: str = ""
    #: Anything the DM wants respected that is in no book -- what happened at
    #: the table since this thing was minted.
    note: str = ""


@router.get("/section")
def read_section(section_id: str, campaign: str | None = None) -> dict:
    """The prose of one section, canon or campaign, for a person to read.

    THE THING A DM DOES AT A TABLE. The running order listed 547 headings and
    clicking one did nothing; the material panel listed a cast and clicking one
    did nothing. So "show me the scene I wrote" meant asking the chat and
    hoping retrieval surfaced it -- for prose sitting one query away.

    A CAMPAIGN SECTION IS ONLY READABLE FROM ITS OWN CAMPAIGN. Canon is
    readable by anyone: it is the book. The `campaign` argument is the caller
    saying which table it is at, and a campaign section belonging to another
    one is not found rather than refused -- from this endpoint's side there is
    nothing there.
    """
    with read_only_session() as session:
        row = session.run(
            """
            MATCH (s:Section {id:$id})
            WHERE s.plane = 'canon' OR s.campaign = $campaign
            OPTIONAL MATCH (c:Chapter)-[:HAS_SECTION]->(s)
            OPTIONAL MATCH (s)-[:DERIVED_FROM]->(cited:Section)
            OPTIONAL MATCH (m:Mention)-[:IN_SECTION]->(s)
            OPTIONAL MATCH (m)-[:REFERS_TO]->(named:Entity)
            OPTIONAL MATCH (named)-[edge]->(far:Entity)
            // BOTH ENDS HAVE TO BE IN THIS SECTION. Reading `The Corsair
            // Ambush`, "Connected" listed `Revel's End contains Stables` and
            // two more of the same -- true of Revel's End, which the prose
            // mentions in passing, and nothing to do with the scene. One end
            // here is a second-order fact about somewhere else; both ends here
            // is a fact about what is happening in this section.
            WHERE (far.plane = 'canon' OR far.campaign = $campaign)
              AND (far)<-[:REFERS_TO]-(:Mention)-[:IN_SECTION]->(s)
            RETURN s.id AS section_id, s.heading AS heading, s.text AS text,
                   s.plane AS plane, s.kind AS kind, s.invented AS invented,
                   s.from_canon AS from_canon, s.from_yours AS from_yours,
                   s.from_context AS from_context,
                   s.edited AS edited, c.slug AS chapter,
                   collect(DISTINCT cited.heading) AS cites,
                   // THE NAMES THIS PROSE ACTUALLY USES, from the mention
                   // triangle rather than from matching strings in the reader.
                   // The graph is the authority on which entity a word refers
                   // to; a client scanning for names of its own would disagree
                   // with retrieval the first time two things shared one.
                   //
                   // `display_name` OR `surface`: canon mentions carry the
                   // first, homebrew writers the second. One fact under two
                   // property names, which is worth knowing and not worth a
                   // migration in the middle of a feature.
                   collect(DISTINCT {
                     entity_id: named.id, name: named.name, kind: named.kind,
                     plane: named.plane,
                     surface: coalesce(m.display_name, m.surface, named.name)
                   }) AS mentions,
                   // ONE HOP OUT, for reference while reading. Everything this
                   // section names is already underlined in the prose; this is
                   // what those things are CONNECTED to, which the prose does
                   // not say and the graph does. A DM reading a scene wants
                   // "what else is this touching" without leaving it.
                   collect(DISTINCT {
                     from: named.name, rel: type(edge), to: far.name,
                     to_id: far.id, plane: far.plane, status: edge.status
                   }) AS connections
            """,
            {"id": section_id, "campaign": campaign},
        ).single()
    if row is None:
        raise HTTPException(status_code=404, detail=f"no section {section_id!r} here")

    found = dict(row)
    for field in ("invented", "from_canon", "from_yours", "from_context"):
        raw = found.get(field)
        # Stored as JSON on the node; a reader wants the list, and a canon
        # section has none of these at all.
        found[field] = json.loads(raw) if raw else []
    found["cites"] = [c for c in found["cites"] if c]
    found["mentions"] = [m for m in found["mentions"] if m.get("entity_id")]
    found["connections"] = [
        c for c in found["connections"] if c.get("rel") and c.get("to")
    ]
    return found


@router.post("/draft-expansion")
async def draft_expansion(request: DraftRequest) -> dict:
    """Write a draft for something the campaign already holds. Stores nothing.

    THE ELEMENT'S OWN RECORD IS THE CONTEXT. A stub knows its kind, its role
    and the scene that introduced it, and handing that to the generator is the
    difference between "write me an NPC" and "write me THIS NPC" -- which is
    the whole reason the record is stored rather than left in the prose.

    A separate endpoint from `/lab/generate` because the two differ in what
    they may produce: that one mints, this one describes something that
    already exists, and a card that confused them would offer Store on a path
    that raises `AlreadyStored`.
    """
    from backend.agents import canon_context, generator
    from backend.canon.retrieval import CanonRetriever
    from backend.core.config import settings

    with read_only_session() as session:
        row = session.run(
            """
            MATCH (e:Entity {plane:'campaign', id:$id, campaign:$c})
            OPTIONAL MATCH (root:Section {id:e.cluster})
            OPTIONAL MATCH (own:Section {expands:e.id})
            RETURN e.name AS name, e.kind AS kind, e.role AS role,
                   root.heading AS introduced_in, root.text AS scene,
                   own.id AS own_section
            """,
            {"id": request.entity_id, "c": request.campaign},
        ).single()
        if row is None:
            raise HTTPException(status_code=404, detail=f"no {request.entity_id!r} here")
        element = dict(row)
        found = {c.slug: c for c in store.read_campaigns(session)}
        campaign = found.get(request.campaign)

    if element["own_section"]:
        raise HTTPException(
            status_code=409,
            detail=(
                f"{element['name']} already has a write-up. Delete it first if "
                "you want a new one."
            ),
        )

    book = (campaign.books[0] if campaign and campaign.books else "cos")
    retriever = CanonRetriever(book=book, campaign=request.campaign)
    retrieval = retriever.retrieve(element["name"])

    told = [f"{element['name']} is {element['role'] or 'something this table made'}"]
    if element["introduced_in"]:
        told.append(f"introduced in {element['introduced_in']}")
    if element["scene"]:
        told.append(f"which reads: {element['scene'][:400]}")
    if request.note.strip():
        told.append(request.note.strip())

    model = request.model or settings.openai_model
    drafted = await generator.generate(
        _client(),
        kind=element["kind"] or "lore",
        subject=element["name"],
        retrieval=retrieval,
        depth=canon_context.Depth(),
        model=model,
        context=generator.GenerationContext(
            entities=(element["name"],), note=". ".join(told) + "."
        ),
    )
    anchor, chapters = canon_context.suggest_anchor(retrieval)
    return drafted.as_dict() | {
        "model": model,
        # The card routes Store to `/expand` on seeing this, so a draft about
        # an existing thing can never take the minting path.
        "expands": request.entity_id,
        "anchor": anchor,
        "relevant_chapters": list(chapters),
    }


def _client():
    from openai import AsyncOpenAI

    from backend.core.config import settings

    return AsyncOpenAI(api_key=settings.openai_api_key)


@router.post("/expand")
def expand_element(request: ExpandRequest) -> dict:
    """Write prose for an existing element. Creates no entity."""
    _resolved, bad = homebrew.cited_sections(
        [*request.from_canon, *request.from_yours], request.sources
    )
    if bad:
        raise HTTPException(
            status_code=400,
            detail=f"{len(bad)} citation(s) point at nothing that was shown: {bad[:3]}",
        )
    try:
        with neo4j_session() as session:
            stored = session.execute_write(
                lambda tx: homebrew.expand(
                    tx,
                    slug=request.campaign,
                    entity_id=request.entity_id,
                    body=request.body,
                    generated_body=request.generated_body or request.body,
                    from_canon=request.from_canon,
                    from_yours=request.from_yours,
                    invented=request.invented,
                    from_context=request.from_context,
                    sources=request.sources,
                    anchor=request.anchor,
                    model=request.model,
                )
            )
    except homebrew.NotStored as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except homebrew.AlreadyExpanded as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return stored.as_dict()


#: How much either side of a mention to keep when no sentence end is found --
#: enough to be a claim, short enough to stay a quote.
_QUOTE_WINDOW = 220


def _sentences_at(text: str, offsets: list[int], limit: int = 3) -> list[str]:
    """The sentences that actually name the thing, quoted exactly.

    A LIST OF HEADINGS IS NOT AN ANSWER. "Named in: Trek to the Prison" tells a
    DM where to go looking; "directs them to report to a ship called the Jolly
    Pelican the following dawn" tells them what it IS. The offsets have been
    stored all along and the difference between the two is one hop.

    QUOTED, NEVER SUMMARISED. Everything else this endpoint returns is the
    graph's own record; this is the book's words, and a paraphrase here would
    be the one kind of sentence a DM has no way to check.

    Sentence bounds by punctuation, falling back to a window when a section has
    none — headings and table rows often do not. A quote that runs on is worse
    than one that stops early, so the window is small.
    """
    found: list[str] = []
    for offset in offsets[:limit]:
        if not 0 <= offset < len(text):
            continue
        start = text.rfind(".", 0, offset) + 1
        end = text.find(".", offset)
        if end == -1 or end - start > _QUOTE_WINDOW * 2:
            start = max(0, offset - _QUOTE_WINDOW)
            end = min(len(text), offset + _QUOTE_WINDOW)
        quote = " ".join(text[start : end + 1].split()).strip()
        if quote and quote not in found:
            found.append(quote)
    return found


@router.get("/entity")
def read_entity(entity_id: str, campaign: str | None = None) -> dict:
    """What the graph holds about one thing, for a reader who clicked its name.

    BOTH PLANES, because a DM reading their own scene clicks straight through
    to `Jolly Pelican`, which is the book's. Scoped the same way `/section` is:
    canon is open, campaign material only to the campaign that owns it.

    WHERE ELSE IT IS NAMED is the useful half of this. A name in isolation is a
    dictionary entry; the list of scenes and sections that mention it is what
    lets a DM follow a thread — and it is the same triangle the highlight was
    drawn from, so the two cannot disagree.
    """
    with read_only_session() as session:
        row = session.run(
            """
            MATCH (e:Entity {id:$id})
            WHERE e.plane = 'canon' OR e.campaign = $campaign
            OPTIONAL MATCH (own:Section {expands:e.id})
            OPTIONAL MATCH (e)<-[:REFERS_TO]-(m:Mention)-[:IN_SECTION]->(sec:Section)
            WHERE sec.plane = 'canon' OR sec.campaign = $campaign
            RETURN e.id AS entity_id, e.name AS name, e.kind AS kind,
                   e.plane AS plane, e.role AS role, e.invented AS invented,
                   labels(e) AS labels, own.id AS own_section,
                   collect(DISTINCT {
                     section_id: sec.id, heading: sec.heading, plane: sec.plane,
                     // The TEXT and the offsets, so the card can quote what
                     // each place actually says rather than only naming it.
                     text: sec.text, offsets: m.offsets
                   }) AS named_in
            """,
            {"id": entity_id, "campaign": campaign},
        ).single()
    if row is None:
        raise HTTPException(status_code=404, detail=f"no entity {entity_id!r} here")
    found = dict(row)
    found["invented"] = json.loads(found["invented"]) if found["invented"] else []
    found["named_in"] = [
        {
            "section_id": where["section_id"],
            "heading": where["heading"],
            "plane": where["plane"],
            "says": _sentences_at(where.get("text") or "", where.get("offsets") or []),
        }
        for where in found["named_in"]
        if where.get("section_id")
    ]
    found["labels"] = [x for x in (found["labels"] or []) if x != "Entity"]
    return found


class RoleRequest(BaseModel):
    campaign: str
    entity_id: str
    role: str


@router.post("/role")
def set_role(request: RoleRequest) -> dict:
    """Change the one line a stub is made of."""
    with neo4j_session() as session:
        try:
            return session.execute_write(
                lambda tx: homebrew.rename_role(
                    tx,
                    slug=request.campaign,
                    entity_id=request.entity_id,
                    role=request.role,
                )
            )
        except homebrew.NotStored as refused:
            raise HTTPException(status_code=404, detail=str(refused)) from refused


class DeriveRequest(BaseModel):
    campaign: str
    section_id: str
    model: str | None = None


@router.post("/derive-edges")
async def derive_edges(request: DeriveRequest) -> dict:
    """Read a stored section back and propose the relationships in it.

    RUN AFTER A WRITE OR AN EDIT, not inside one. It is a model call and a real
    cost, and holding a Neo4j transaction open across one would be trading a
    lock for a network round trip.

    IT ASKS ONLY ABOUT RELATIONSHIPS, and only between names the mention scan
    already resolved. `annotate` -- the second pass a cluster gets -- was the
    obvious thing to reuse and was tried first, but it is element-first: it
    reads prose looking for things to MINT, and edges are what falls out
    afterwards. Pointed at a section whose things already exist, it proposed
    nothing and dropped what it did find as an unoffered element kind. The
    measured lesson behind it still holds -- declaring edges WHILE writing put
    37-51% of them outside the type table, and reading finished prose brought
    it to 27% -- so this reads finished prose too. It just asks the narrower
    question, and one section went from 3 proposals to 7.

    What it writes is `proposed`. The DM asserting a relationship and a model
    guessing one from their sentences are different claims, and the second gets
    dimmed and labelled rather than mixed in with the first.
    """
    from openai import AsyncOpenAI

    from backend.agents import generator
    from backend.graph.schema import IN_SECTION, REFERS_TO

    with read_only_session() as session:
        row = session.run(
            "MATCH (s:Section {id:$id, plane:'campaign', campaign:$c}) "
            "RETURN s.text AS text",
            {"id": request.section_id, "c": request.campaign},
        ).single()
        if row is None:
            raise HTTPException(404, f"no section {request.section_id!r} here")
        body = row["text"] or ""
        # THE NAMES THE SCAN ALREADY FOUND, handed over rather than
        # rediscovered. They are the closed set the answer may use, which is
        # both what makes the question narrow enough to answer well and what
        # makes an out-of-scope edge impossible rather than merely dropped.
        names = tuple(
            r["name"]
            for r in session.run(
                f"""
                MATCH (m:Mention)-[:{IN_SECTION}]->(:Section {{id:$s}})
                MATCH (m)-[:{REFERS_TO}]->(e:Entity)
                RETURN DISTINCT e.name AS name ORDER BY e.name
                """,
                {"s": request.section_id},
            )
        )
    if not body.strip():
        return {"written": 0, "dropped": {}, "note": "nothing written yet to read"}

    model = request.model or settings.openai_model
    # `read_back` refuses fewer than two names itself, so there is no guard
    # here to fall out of step with it.
    edges, error = await generator.read_back(
        AsyncOpenAI(api_key=settings.openai_api_key),
        body=body,
        names=names,
        model=model,
    )
    if error:
        raise HTTPException(502, f"could not read it back: {error}")

    with neo4j_session() as session:
        return session.execute_write(
            lambda tx: homebrew.derive_edges(
                tx, slug=request.campaign, section_id=request.section_id, edges=edges
            )
        )



class NestRequest(BaseModel):
    campaign: str
    section_id: str
    #: What it now sits inside. Empty puts it at the top level.
    parent: str = ""


@router.post("/nest")
def nest(request: NestRequest) -> dict:
    """Put a section INSIDE another, or take it out of one.

    SEQUENCE IS NOT TOUCHED. `/move` reorders; this re-parents; and a story has
    both axes. Conflating them is what made "The Sea Battle Encounter" -- a
    fight during The Sea Battle -- placeable only as its sibling, landing
    before the scene it happens inside.

    CHECKED AGAINST THE ONTOLOGY, and refused in a sentence rather than a code:
    this reaches a person, and "an encounter goes inside a scene, not inside an
    encounter" is the whole explanation.
    """
    with neo4j_session() as session:
        rows = {
            dict(r)["id"]: dict(r)
            for r in session.run(
                "MATCH (s:Section) WHERE s.id IN $ids "
                "RETURN s.id AS id, s.kind AS kind, s.depth AS depth, "
                "s.plane AS plane",
                {"ids": [request.section_id, request.parent] if request.parent
                        else [request.section_id]},
            )
        }
        child = rows.get(request.section_id)
        if child is None:
            raise HTTPException(404, f"no section {request.section_id!r}")
        if request.parent:
            parent = rows.get(request.parent)
            if parent is None:
                raise HTTPException(404, f"no section {request.parent!r}")
            refusal = ontology.refuse(
                ontology.level_of(parent["kind"] or "", parent["depth"]),
                ontology.level_of(child["kind"] or "", child["depth"]),
            )
            if refusal:
                raise HTTPException(422, refusal)
        try:
            return session.execute_write(
                lambda tx: store.set_parent(
                    tx, request.campaign, request.section_id, request.parent
                )
            )
        except ValueError as refused:
            raise HTTPException(404, str(refused)) from refused


class RescanRequest(BaseModel):
    campaign: str


@router.post("/rescan")
def rescan_campaign(request: RescanRequest) -> dict:
    """Read every stored section's prose again, for this campaign.

    NEW WRITES AND EDITS SCAN THEMSELVES, so this is for what predates that --
    and for the day a name is added to a book's `global_names` and becomes
    scannable outside its own chapter, which is not a campaign event at all.
    Both cases are "the graph could see more of this prose than it does", and
    neither announces itself.

    Idempotent by construction: `rescan` reconciles rather than appends, so
    running it twice is running it once.
    """
    with neo4j_session() as session:
        sections = [
            r["id"]
            for r in session.run(
                "MATCH (:Campaign {slug:$c})-[:HAS_SECTION]->(s:Section) "
                "RETURN s.id AS id ORDER BY s.id",
                {"c": request.campaign},
            )
        ]
        totals = {"sections": len(sections), "scanned": 0, "dropped": 0}
        for section_id in sections:
            result = session.execute_write(
                lambda tx, s=section_id: homebrew.rescan(
                    tx, slug=request.campaign, section_id=s
                )
            )
            totals["scanned"] += result["scanned"]
            totals["dropped"] += result["dropped"]
    return totals


class EditRequest(BaseModel):
    campaign: str
    section_id: str
    body: str


@router.post("/edit")
def edit_section(request: EditRequest) -> dict:
    """Rewrite the prose of something this campaign already stored.

    Refuses anything that is not this campaign's, which includes the book.
    404 rather than 403: whether an id exists elsewhere is not this caller's
    business.
    """
    with neo4j_session() as session:
        try:
            return session.execute_write(
                lambda tx: homebrew.edit(
                    tx,
                    slug=request.campaign,
                    section_id=request.section_id,
                    body=request.body,
                )
            )
        except homebrew.NotEditable as refused:
            raise HTTPException(status_code=404, detail=str(refused)) from refused


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
