"""What a declared cluster WOULD write, decided without touching Neo4j.

`plan_write` does this for a book chapter; this does it for one generation's
manifest. It borrows that module's discipline -- every rejection counted and
named, nothing coerced to the nearest valid thing, refuse rather than guess --
and none of its extraction front end, because a cluster's candidates were
declared by their author rather than inferred from prose by a reader.

PURE, AND A TEST PINS THAT IT STAYS PURE. No Neo4j import, no session, no I/O:
the caller reads what this needs and hands it in as plain data. Same reason
`chain.py` is pure -- a rule that only exists inside a transaction cannot be
argued with, and the card calls this on every edit, so it has to be cheap.

EDGES ARE PLANNED NOW, AND THE MEASUREMENT THAT ONCE REFUSED THEM IS WHY THEY
CAN BE. Forty generations across both books said a model declares elements it
agrees with itself about (0.78 over fixed prose, against a 0.75 gate) and edges
it does not (0.64, with 27% type-impossible against a 20% gate). Both numbers
still stand. What changed is what is done about them.

The 27% is now REMOVED rather than tolerated: `constraints.report_edges` is the
same domain/range check canon extraction runs, so what survives is type-valid
by construction and the count of what did not is named on the card. A rate that
was a reason to store nothing becomes a filter once something deterministic can
apply it.

The 0.64 is not a filter and does not need to be. Instability is fatal where
nothing reviews the output -- canon extraction writes what it infers, so two
runs disagreeing means the graph is a coin toss. Here a person reads every edge
and ticks it before it is written. A second draw proposing different
relationships is a different suggestion to a DM who is already choosing, not a
different fact about the book. That is the whole difference between this path
and the extractor, and it is why the same number blocks one and not the other.

BOTH ENDPOINTS MUST BE IN THE CLUSTER. An edge naming a canon entity is a
cross-plane edge, and those are readable from neither plane as things stand --
so they are dropped and counted rather than written somewhere nobody looks.
`evals/baselines/manifest-*.json` holds the runs.
"""

from __future__ import annotations

from dataclasses import dataclass, field

#: A generated name that slugifies to nothing has no id to be given.
from backend.campaign.homebrew import LABELS, slugify
from backend.campaign.model import mint_id
from backend.canon.aliases import normalize
from backend.canon.constraints import report_edges
from backend.canon.models import CandidateEdge, CandidateNode


@dataclass(frozen=True)
class PlannedElement:
    """One thing a cluster declares, with the id it would be given."""

    name: str
    kind: str
    role: str
    entity_id: str
    from_canon: tuple[dict, ...] = ()
    invented: tuple[str, ...] = ()
    #: A canon entity of the same name, when one exists. Its presence makes the
    #: plan unstorable until the DM says what it means -- see `Collision`.
    collides_with: str = ""


#: What a DM may say about a name that already exists in the book.
_RESOLUTIONS = ("link", "rename")


@dataclass(frozen=True)
class Collision:
    """A declared element sharing a name with something in the drawn book.

    NOT RESOLVED AUTOMATICALLY IN EITHER DIRECTION. Minting a second node
    silently leaves two things answering to one name through `resolve_name`,
    which is the trap; folding into the canon one silently rewrites what the
    book's NPC is. The DM did not name the canon entity, so either choice is a
    guess about identity, and this refuses to make it.

    `AlreadyStored` refuses an intra-campaign clash for the mirror reason: there
    the DM DID name both, so two things named alike are two things.
    """

    name: str
    element_kind: str
    canon_id: str
    #: `link` uses the canon entity and mints nothing; `rename` gives the
    #: element a new name.
    #:
    #: THERE IS NO "MINT IT ANYWAY" CHOICE, and the reason is a constraint
    #: rather than a policy: `Alias.name` is globally unique, so a second node
    #: spelled the same cannot exist. An element that keeps a canon name shares
    #: that alias node and the ambiguity travels -- which `BY_ALIAS` already
    #: calls legitimate -- but it is not a thing a DM can choose here, because
    #: what they would be choosing is invisible to them.
    choices: tuple[str, ...] = _RESOLUTIONS


@dataclass(frozen=True)
class ClusterPlan:
    """Exactly what a store would write, and everything it would not."""

    campaign: str
    elements: tuple[PlannedElement, ...] = ()
    collisions: tuple[Collision, ...] = ()
    #: `(name, canon_id)` for elements the DM said were the book's own. NOT a
    #: drop, though the element mints nothing: the scene genuinely involves
    #: that entity, and saying so is the whole point of choosing `link`.
    links: tuple[tuple[str, str], ...] = ()
    #: Reason -> count. Never a bare total: "3 dropped" tells a reader nothing
    #: about whether the generation or the rules were at fault.
    dropped: dict = field(default_factory=dict)
    #: Relationships that survived the type check, each between two things
    #: this cluster mints. `(source, target, rel_type)` by NAME, since ids are
    #: on `elements` and a card renders names.
    edges: tuple[tuple[str, str, str], ...] = ()
    #: Declared relationships thrown away, by reason. Never a bare total: "3
    #: dropped" says nothing about whether the model or the rules were at
    #: fault, and this is the count the card prints.
    edges_dropped: dict = field(default_factory=dict)
    #: Relationships the model wrote BACKWARDS, held in the direction that
    #: would be legal. Offered rather than applied: `Strahd SEEKS Ireena` and
    #: `Ireena SEEKS Strahd` are different claims about the same two nodes, so
    #: flipping one silently would be inventing a fact. A person is asked.
    edges_reversible: tuple[tuple[str, str, str], ...] = ()

    @property
    def storable(self) -> bool:
        """False while any collision is unresolved. A plan is not a write."""
        return not self.collisions

    def as_dict(self) -> dict:
        return {
            "campaign": self.campaign,
            "elements": [
                {
                    "name": e.name,
                    "kind": e.kind,
                    "role": e.role,
                    "entity_id": e.entity_id,
                    "from_canon": list(e.from_canon),
                    "invented": list(e.invented),
                    "collides_with": e.collides_with,
                }
                for e in self.elements
            ],
            "collisions": [
                {
                    "name": c.name,
                    "kind": c.element_kind,
                    "canon_id": c.canon_id,
                    "choices": list(c.choices),
                }
                for c in self.collisions
            ],
            "links": [{"name": n, "canon_id": c} for n, c in self.links],
            "dropped": dict(self.dropped),
            "edges": [
                {"source": s, "target": t, "rel_type": r} for s, t, r in self.edges
            ],
            "edges_dropped": dict(self.edges_dropped),
            "edges_reversible": [
                {"source": s, "target": t, "rel_type": r}
                for s, t, r in self.edges_reversible
            ],
            "storable": self.storable,
        }


def plan_cluster(
    *,
    campaign: str,
    elements,
    edges=(),
    root_name: str = "",
    root_kind: str = "",
    accept_reversed: frozenset[str] = frozenset(),
    canon_aliases: frozenset[tuple[str, str]] = frozenset(),
    approved: frozenset[str] | None = None,
    existing_ids: frozenset[str] = frozenset(),
    resolutions: dict[str, str] | None = None,
) -> ClusterPlan:
    """Turn a declared manifest into the exact write it implies.

    `approved` is the subset of element NAMES the DM kept; None means all of
    them, which is the state a freshly generated card is in. `resolutions` maps
    a colliding name to the choice a DM made about it.

    `root_name`/`root_kind` are the generation ITSELF -- the scene or the
    quest -- which is a node like any other and the one most edges point at.
    Omitting it dropped every "the ambush INVOLVES the bosun" a model declared,
    which is most of what it declares.

    Order matters and is fixed: reject unapproved, drop unusable, mint ids,
    then scan collisions. Scanning before minting would report a collision for
    something about to be dropped.
    """
    approved_names = None if approved is None else {n.casefold() for n in approved}
    chosen = {k.casefold(): v for k, v in (resolutions or {}).items()}
    by_normalized = dict(canon_aliases)

    dropped: dict[str, int] = {}

    def drop(reason: str) -> None:
        dropped[reason] = dropped.get(reason, 0) + 1

    planned: list[PlannedElement] = []
    collisions: list[Collision] = []
    links: list[tuple[str, str]] = []
    minted: set[str] = set()

    for element in elements:
        name = str(element.get("name") or "").strip()
        kind = str(element.get("kind") or "").strip().lower()
        if approved_names is not None and name.casefold() not in approved_names:
            drop("rejected by the DM")
            continue

        slug = slugify(name)
        if not slug:
            # A name of punctuation alone has no id, and inventing one would
            # give the DM a node they can never say out loud.
            drop("name slugifies to nothing")
            continue

        entity_id = mint_id(campaign, slug)
        if entity_id in existing_ids:
            # The campaign already holds this. Refused rather than merged, the
            # rule `AlreadyStored` states, checked here so the card can say so
            # before a person presses store.
            drop("already in this campaign")
            continue
        if entity_id in minted:
            drop("two elements mint the same id")
            continue

        canon_id = by_normalized.get(normalize(name), "")
        choice = chosen.get(name.casefold(), "")
        # An UNRECOGNISED resolution leaves the collision standing rather than
        # falling through to a write. A typo in a choice must not become a
        # decision nobody made.
        if canon_id and choice not in _RESOLUTIONS:
            collisions.append(Collision(name=name, element_kind=kind, canon_id=canon_id))
        elif canon_id and choice == "link":
            # No node minted, but the link is RECORDED. It was a drop and
            # nothing else, which made "use the book's" a decision with no
            # consequence: the DM told the system their scene involves the
            # book's Marta Marthannis, and asking about her tomorrow surfaced
            # nothing. The canon node is still never touched -- what gets
            # written is a mention pointing AT it, which says "this scene
            # involves her" without claiming to know who she is.
            links.append((name, canon_id))
            continue

        minted.add(entity_id)
        planned.append(
            PlannedElement(
                name=name,
                kind=kind,
                role=str(element.get("role") or "").strip(),
                entity_id=entity_id,
                from_canon=tuple(element.get("from_canon") or ()),
                invented=tuple(element.get("invented") or ()),
                collides_with=canon_id,
            )
        )

    kept_edges, edges_dropped, reversible = _plan_edges(
        edges, planned, root_name, root_kind, accept_reversed
    )
    return ClusterPlan(
        campaign=campaign,
        elements=tuple(planned),
        collisions=tuple(collisions),
        links=tuple(links),
        dropped=dropped,
        edges=kept_edges,
        edges_dropped=edges_dropped,
        edges_reversible=reversible,
    )


def edge_key(source: str, target: str, rel_type: str) -> str:
    """How a reversed edge is named when a DM accepts one. Folded, so the key
    the card sends back cannot miss on capitalisation the model chose."""
    return f"{source.casefold()}|{target.casefold()}|{rel_type.upper()}"


def _plan_edges(
    edges,
    planned: list[PlannedElement],
    root_name: str,
    root_kind: str,
    accept_reversed: frozenset[str] = frozenset(),
) -> tuple[tuple[tuple[str, str, str], ...], dict, tuple[tuple[str, str, str], ...]]:
    """Which declared relationships are writable. `(kept, dropped_by_reason)`.

    THE TYPE CHECK IS THE SAME ONE CANON RUNS. `report_edges` reads
    `RELATIONSHIP_DOMAIN_RANGE`, so a homebrew edge has to satisfy exactly what
    an extracted one does -- there is one table and one answer to "can an ITEM
    contain an NPC", not a second, laxer one for material a DM wrote.

    ENDPOINTS ARE MATCHED BY NAME, folded, against what this cluster mints plus
    the generation itself. Anything else is a cross-plane edge into canon, and
    those are readable from neither plane as things stand, so they are dropped
    with that said rather than written where nobody would find them.

    A REJECTED ELEMENT TAKES ITS EDGES WITH IT. `planned` is already the
    approved set, so unticking the bosun silently removes the relationships
    that named him -- which is what unticking him means.

    A BACKWARDS EDGE IS OFFERED, NOT FLIPPED. Measured across twenty-two
    declared edges, four were type-impossible one way round and legal the
    other -- `Vistani Camp THREATENS Wolves`, `Church of Barovia LOCATED_IN
    Kolyan Indirovich`. Every one of them was a real relationship pointing the
    wrong way. Turning them round automatically would still be guessing:
    `Strahd SEEKS Ireena` and its reverse are different claims about one pair,
    and the extractor lists reversal among its four measured failure modes for
    that reason. So the legal direction is offered and a person accepts it,
    which is the shape the name-collision resolution already uses.
    """
    dropped: dict[str, int] = {}

    def drop(reason: str) -> None:
        dropped[reason] = dropped.get(reason, 0) + 1

    nodes = [
        CandidateNode(name=e.name, entity_type=LABELS.get(e.kind, "LORE"))
        for e in planned
    ]
    if root_name:
        nodes.append(
            CandidateNode(name=root_name, entity_type=LABELS.get(root_kind, "LORE"))
        )
    known = {node.name.casefold() for node in nodes}

    candidates: list[CandidateEdge] = []
    for edge in edges or ():
        source = str(edge.get("source") or "").strip()
        target = str(edge.get("target") or "").strip()
        if source.casefold() not in known or target.casefold() not in known:
            drop("an endpoint is not in this cluster")
            continue
        candidates.append(
            CandidateEdge(
                source_name=source,
                target_name=target,
                rel_type=str(edge.get("rel_type") or "").strip().upper(),
            )
        )

    report = report_edges(nodes, candidates)
    bad = {violation.edge_index for violation in report.violations}
    reversible: list[tuple[str, str, str]] = []
    accepted: list[tuple[str, str, str]] = []
    for violation in report.violations:
        if violation.reversal_would_pass:
            edge = candidates[violation.edge_index]
            turned = (edge.target_name, edge.source_name, edge.rel_type)
            (accepted if edge_key(*turned) in accept_reversed else reversible).append(
                turned
            )
            continue
        # NAMED, not counted as one lump. "SEEKS wants an NPC, got an ITEM" is
        # a different thing to know than "6 dropped", and reversal is one of
        # the extractor's four measured failure modes -- so a reversed edge
        # says so, since that is a fixable prompt problem rather than noise.
        drop(f"{violation.rel_type}: {violation.reason}")

    kept = tuple(
        [
            (edge.source_name, edge.target_name, edge.rel_type)
            for index, edge in enumerate(candidates)
            if index not in bad
        ]
        + accepted
    )
    return kept, dropped, tuple(reversible)
