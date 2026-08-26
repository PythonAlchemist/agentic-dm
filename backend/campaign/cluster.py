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

ELEMENTS ONLY, AND THE REASON IS MEASURED. Forty generations across both books
said a model declares elements it agrees with itself about (0.78 agreement over
fixed prose, against a 0.75 gate) and edges it does not (0.64, and 27% of them
type-impossible against a 20% gate). So elements are planned and written;
declared edges are COUNTED AND REPORTED but not stored, and the count is shown
to the DM rather than swallowed -- a model that proposed six relationships and
had none kept should say so on the card. `evals/baselines/manifest-*.json`
holds the runs.
"""

from __future__ import annotations

from dataclasses import dataclass, field

#: A generated name that slugifies to nothing has no id to be given.
from backend.campaign.homebrew import slugify
from backend.campaign.model import mint_id
from backend.canon.aliases import normalize


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
    #: Reason -> count. Never a bare total: "3 dropped" tells a reader nothing
    #: about whether the generation or the rules were at fault.
    dropped: dict = field(default_factory=dict)
    #: Declared relationships not stored in this slice, counted so the card can
    #: say so plainly rather than appearing to have lost them.
    edges_deferred: int = 0

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
            "dropped": dict(self.dropped),
            "edges_deferred": self.edges_deferred,
            "storable": self.storable,
        }


def plan_cluster(
    *,
    campaign: str,
    elements,
    edges=(),
    canon_aliases: frozenset[tuple[str, str]] = frozenset(),
    approved: frozenset[str] | None = None,
    existing_ids: frozenset[str] = frozenset(),
    resolutions: dict[str, str] | None = None,
) -> ClusterPlan:
    """Turn a declared manifest into the exact write it implies.

    `approved` is the subset of element NAMES the DM kept; None means all of
    them, which is the state a freshly generated card is in. `resolutions` maps
    a colliding name to the choice a DM made about it.

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
            # No node minted: the cluster points at the book's entity instead.
            # The canon node is not touched -- linking is about what this table
            # says the NPC DOES, never about who the book says they are.
            drop("linked to a canon entity instead of minting")
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

    return ClusterPlan(
        campaign=campaign,
        elements=tuple(planned),
        collisions=tuple(collisions),
        dropped=dropped,
        edges_deferred=len(tuple(edges)),
    )
