"""What a campaign IS, as constants and predicates. No queries, no I/O.

THE CAMPAIGN IS THE TOP-LEVEL THING, not a bag of homebrew hanging off a book.
A table runs Prisoner 13 and adds a sea battle on the voyage; the campaign
contains both, and a campaign with no book at all is equally legal. So `Campaign`
draws on zero or more books rather than belonging to one.

WHY A CHAIN AND NOT AN INDEX. The canon spine orders itself with integer
properties -- `index`, `parent_index`, `depth` -- and must keep doing so: the
index is baked into every section id (`cos:the-village-of-barovia#4`), every
evaluation question's gold reference, and every stored citation, and the spine
is DERIVED, deleted and rewritten whole every time a chapter is re-extracted.
Properties are trivially idempotent under that.

A campaign's order is the opposite kind of thing. It is a human's decisions --
insert here, skip that, move this -- and it must be rewireable without
re-minting anything. So it is edges: `NEXT`, per campaign, over a chain seeded
from the spine. The same fact from two sides: re-derivable things want
properties, decisions want pointers.

WHAT THIS COSTS, SAID PLAINLY. A chain fails worse than an index: a missing
pointer truncates the order silently and a duplicated one loops it, where a bad
integer is a gap you find by sorting. That is accepted HERE and refused for
canon, because a campaign chain is small (~900 edges at most), every walk is
bounded, every mutation asserts integrity inside its own transaction, and every
mutation is logged so a broken chain can be replayed. None of those mitigations
are available to a spine that is rewritten by a batch job.
"""

from __future__ import annotations

from dataclasses import dataclass

#: Everything a campaign writes. The second inhabitant of the plane axis, which
#: was designed for from the beginning and empty until now.
CAMPAIGN_PLANE = "campaign"

#: Asserted by the DM: authoritative at this table, making no claim about the
#: book. A third value beside `accepted` and `proposed` rather than a reuse of
#: either, because status is what the model reads to decide how far to trust a
#: line, and both existing values would lie to it. `accepted` says "derived from
#: the book's own structure, incapable of hallucinating" -- filing a DM's
#: invention there tells the model the book said it. `proposed` says "roughly a
#: third are wrong, never state one as fact" -- which hedges about facts the DM
#: authored and owns. Neither is true of "I decided this."
AUTHORED = "authored"

#: Read by the DM and judged wrong. The verdict that was missing.
#:
#: `accepted` and `authored` are both ways of saying yes, and there was no way
#: of saying no. Deleting a proposed edge does not mean no: `derive_edges` reads
#: the prose again and proposes it again, so a guess the DM threw out came back
#: on the next run and the review loop never closed. 2,145 proposed edges stood
#: against 593 accepted and 7 authored, with one exit between them.
#:
#: A STATUS RATHER THAN A DELETION, because the fact worth keeping is the
#: JUDGEMENT. "Nobody has looked at this" and "somebody looked and said no" are
#: different states, and an absent edge cannot tell them apart -- which is the
#: same argument `AUTHORED` makes about not reusing `accepted`.
#:
#: NEVER SURFACED. `split_by_status` files everything that is not `accepted`
#: under proposed, so a rejected edge reaching a reader would be dimmed rather
#: than gone. The read queries exclude it instead, so the only thing that ever
#: sees one is the writer checking whether to propose it again.
REJECTED = "rejected"

#: The campaign's first section. Exists if and only if the chain is non-empty,
#: which is the invariant a pure-homebrew campaign starts out violating in the
#: only legal way: no sections, no start.
STARTS_AT = "STARTS_AT"

#: The chain itself. Carries `campaign` as a PROPERTY, never as part of the
#: relationship type: two campaigns may chain the same canon sections, and a
#: per-campaign type would be exactly the dynamic-label interpolation the canon
#: read path refuses on principle.
NEXT = "NEXT"

#: The DM cut this section from their running order. RECORDED, never inferred
#: from absence: without it, reconciliation cannot tell "the DM removed this"
#: from "this section is new since the campaign was seeded", and those need
#: opposite repairs. The same reason a rejected edge is stamped rather than
#: deleted.
SKIPPED = "SKIPPED"

#: Which books the campaign takes as canon. Zero is legal and means a wholly
#: invented world.
DRAWS_ON = "DRAWS_ON"

#: What a campaign section sits INSIDE, canon or campaign.
#:
#: SEPARATE FROM `NEXT`, which is sequence. A story has both and the chain only
#: ever had one, so an encounter that happens DURING a scene could only be
#: placed as its sibling -- landing before the thing it occurs inside. Two
#: axes, two edges: reordering siblings leaves containment alone, and
#: re-parenting leaves the neighbours' order alone.
PART_OF = "PART_OF"

#: Ids minted by a campaign. `hb:` marks plane-of-origin in the id itself, so a
#: citation is self-identifying without a lookup, and guarantees a campaign slug
#: can never collide with a book prefix -- `books.BookScheme` owns bare ones.
ID_PREFIX = "hb"


def campaign_prefix(slug: str) -> str:
    """The id prefix every node this campaign mints carries."""
    return f"{ID_PREFIX}:{slug}:"


def mint_id(slug: str, name_slug: str) -> str:
    """`hb:<campaign>:<name>`. A campaign is one continuous world, so names
    merge across it -- the `anthology: false` rule, for the same reason: a table
    that says "the harbormaster" twice means one person."""
    return f"{campaign_prefix(slug)}{name_slug}"


def is_campaign_id(node_id: str) -> bool:
    return node_id.startswith(f"{ID_PREFIX}:")


@dataclass(frozen=True)
class Campaign:
    """One table. `books` is what it draws on -- possibly nothing."""

    slug: str
    name: str
    books: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not self.slug:
            raise ValueError("a campaign needs a slug")

    @property
    def prefix(self) -> str:
        return campaign_prefix(self.slug)

    @property
    def is_pure_homebrew(self) -> bool:
        return not self.books


# -- invariants -------------------------------------------------------------
#
# Pure predicates over plain data, so the rules can be tested and asserted
# inside a write transaction without either place restating them.


def start_matches_chain(has_start: bool, chain_length: int) -> bool:
    """`STARTS_AT` exists exactly when the chain is non-empty."""
    return has_start == (chain_length > 0)


def every_section_placed(
    spine_ids: frozenset[str], in_chain: frozenset[str], skipped: frozenset[str]
) -> frozenset[str]:
    """Sections of a drawn book that are neither in the chain nor skipped.

    Empty is the invariant. A non-empty result is the reconcile case -- almost
    always a chapter harvested after the campaign was seeded, which is a real
    thing that happened to this repo the day this was designed.
    """
    return spine_ids - in_chain - skipped


def authored_is_never_canon(status: str, plane: str) -> bool:
    """No `authored` edge may sit on the canon plane.

    A human asserting something about the BOOK goes through `accept_edges`,
    which checks the claim against the book's own sentence and stamps who read
    it. `authored` means "true at my table", and a table cannot promote its own
    invention into canon by writing a different word.
    """
    return not (status == AUTHORED and plane != CAMPAIGN_PLANE)
