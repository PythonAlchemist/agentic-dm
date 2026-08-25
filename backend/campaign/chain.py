"""The running order, planned as pointer rewires. Pure: no Neo4j, no I/O.

Every mutation returns a `Rewire` -- what to unlink, what to link, and whether
the start moved -- which a caller applies in ONE transaction and then asserts
`integrity` on before committing. The split exists for the reason `plan_write`
gives: what a change WOULD do should be printable without a write open, and the
rules should be testable without a database.

THE CHAIN IS A LINKED LIST AND THAT IS A REAL RISK. A dropped pointer truncates
a DM's running order silently; a duplicated one loops it forever. Both are
worse failures than the bad integer an index would give you. Three things make
it acceptable here and none of them are available to canon's spine:

  * every walk is BOUNDED and returns what it found plus a reason for stopping,
    so a loop is reported rather than spun on;
  * `integrity` names every violation, and a caller asserts it inside the same
    transaction that made the change, so a bad rewire rolls back;
  * every applied rewire is logged, so a chain can be re-seeded and replayed.

`section_id` is the only identity used here. Campaign sections are recognised
by their id prefix (`model.is_campaign_id`), never by a flag passed alongside,
because two sources of that truth would be free to disagree.
"""

from __future__ import annotations

from dataclasses import dataclass

from backend.campaign.model import is_campaign_id

#: A chain link, `from -> to`.
Link = tuple[str, str]

#: How far any walk will go before it decides it is looping. Set by the caller
#: from the chain's own length: a correct chain cannot take more steps than it
#: has links, so exceeding that IS the loop, detected without a `seen` set the
#: size of the book.
DEFAULT_BOUND = 10_000


@dataclass(frozen=True)
class Rewire:
    """One planned change: pointers out, pointers in, and where the head goes.

    `sets_start` IS SEPARATE FROM `start` because None means two different
    things. A plan that does not touch the head and a plan that empties the
    chain both want `start=None`, and collapsing them left the last section of
    a chain deleted while `STARTS_AT` went on pointing at it -- a chain that
    reads as one section long forever. `sets_start` says whether `start` is an
    instruction at all.
    """

    unlink: tuple[Link, ...] = ()
    link: tuple[Link, ...] = ()
    start: str | None = None
    sets_start: bool = False
    #: Set when the operation is a no-op, with the reason. A plan that changes
    #: nothing is reported rather than applied silently -- "already skipped" and
    #: "skipped it for you" are different answers to the DM.
    noop: str = ""

    @property
    def changes(self) -> int:
        return len(self.unlink) + len(self.link)


@dataclass(frozen=True)
class Walk:
    """An ordered traversal, and why it ended."""

    order: tuple[str, ...] = ()
    #: `end` (ran out of links), `loop` (revisited a section), or `bound`
    #: (hit the step limit without either). Never silently truncated.
    stopped: str = "end"

    @property
    def looped(self) -> bool:
        return self.stopped == "loop"


def _forward(links: frozenset[Link]) -> dict[str, str]:
    return {a: b for a, b in links}


def _backward(links: frozenset[Link]) -> dict[str, str]:
    return {b: a for a, b in links}


def walk(links: frozenset[Link], start: str | None, bound: int = DEFAULT_BOUND) -> Walk:
    """The running order from `start`, bounded.

    Returns what it found even when it stops badly. A truncated order a caller
    can see is recoverable; one that looks complete is not.
    """
    if start is None:
        return Walk()
    nxt = _forward(links)
    order: list[str] = []
    seen: set[str] = set()
    current: str | None = start
    while current is not None:
        if current in seen:
            return Walk(tuple(order), "loop")
        if len(order) >= bound:
            return Walk(tuple(order), "bound")
        order.append(current)
        seen.add(current)
        current = nxt.get(current)
    return Walk(tuple(order), "end")


def integrity(
    links: frozenset[Link], start: str | None, expected: frozenset[str] | None = None
) -> tuple[str, ...]:
    """Every violation, named. Empty means the chain is sound.

    Asserted inside the transaction that changed the chain, so a rewire that
    would corrupt the order never commits.

    `expected` IS WHAT THE CHAIN SHOULD CONTAIN, and without it this cannot see
    the worst failure it has. Pointer arithmetic alone only knows the sections
    the links mention, so a section that fell out of the chain COMPLETELY --
    every pointer to and from it gone -- leaves a shorter chain that is
    internally perfect. A partially applied move did exactly that in testing:
    five sections went in, four came out, and nothing objected. The caller
    knows the membership it intended; pass it.
    """
    problems: list[str] = []

    out_counts: dict[str, int] = {}
    in_counts: dict[str, int] = {}
    for a, b in links:
        out_counts[a] = out_counts.get(a, 0) + 1
        in_counts[b] = in_counts.get(b, 0) + 1
        if a == b:
            problems.append(f"{a} points at itself")

    for node, n in sorted(out_counts.items()):
        if n > 1:
            problems.append(f"{node} has {n} outgoing links; a section has one successor")
    for node, n in sorted(in_counts.items()):
        if n > 1:
            problems.append(f"{node} has {n} incoming links; a section has one predecessor")

    nodes = {a for a, _ in links} | {b for _, b in links}
    if start is None and links:
        problems.append("the chain has links but no start")
    if start is not None and not links and start:
        pass  # a one-section chain has a start and no links: legal.
    if start is not None and links and start not in nodes:
        problems.append(f"start {start} is not in the chain")
    if start is not None and start in in_counts:
        problems.append(f"start {start} has a predecessor; it is not the head")

    if start is not None:
        found = walk(links, start, bound=len(links) + 2)
        if found.looped:
            problems.append("the chain loops")
        elif found.stopped == "bound":
            problems.append("the chain did not terminate within its own length")
        else:
            unreachable = nodes - set(found.order)
            if unreachable:
                problems.append(
                    f"{len(unreachable)} section(s) unreachable from the start: "
                    f"{sorted(unreachable)[:3]}"
                )

    if expected is not None:
        present = set(walk(links, start, bound=len(links) + 2).order)
        lost = expected - present
        gained = present - expected
        if lost:
            problems.append(
                f"{len(lost)} section(s) fell out of the chain: {sorted(lost)[:3]}"
            )
        if gained:
            problems.append(
                f"{len(gained)} unexpected section(s) in the chain: {sorted(gained)[:3]}"
            )
    return tuple(problems)


def seed_plan(section_ids: list[str]) -> Rewire:
    """The chain a new campaign starts with: the book's own order.

    THE FLATTENING IS THE SPINE'S OWN ORDER, not a tree walk. Section `index`
    is assigned as the document's headings are read, and a document's headings
    are already a pre-order serialisation of its structure -- R1 follows Revel's
    End Locations because the book prints it there. So the caller passes
    `ORDER BY chapter_index, section_index` and this does no re-ordering at all.
    `parent_index`/`depth` stay untouched and go on answering nesting; the chain
    answers only what comes next at this table.
    """
    if not section_ids:
        return Rewire(noop="no sections to seed from")
    links = tuple(zip(section_ids, section_ids[1:]))
    return Rewire(link=links, start=section_ids[0], sets_start=True)


def insert_plan(
    links: frozenset[Link], start: str | None, new_id: str, after: str | None
) -> Rewire:
    """Put `new_id` immediately after `after`, or at the head when it is None."""
    if new_id == after:
        return Rewire(noop=f"{new_id} cannot follow itself")
    nxt = _forward(links)
    if after is None:
        if start is None:
            # The first section of a pure-homebrew campaign. `STARTS_AT` comes
            # into existence exactly here.
            return Rewire(start=new_id, sets_start=True)
        return Rewire(link=((new_id, start),), start=new_id, sets_start=True)

    following = nxt.get(after)
    if following is None:
        return Rewire(link=((after, new_id),))
    return Rewire(unlink=((after, following),), link=((after, new_id), (new_id, following)))


def remove_plan(links: frozenset[Link], start: str | None, section_id: str) -> Rewire:
    """Splice the chain around `section_id`, leaving the order otherwise intact.

    Shared by skip and delete: both take a section out of the running order and
    differ only in what else they record. Keeping one implementation means the
    two cannot drift on the pointer arithmetic, which is the part worth getting
    right once.
    """
    nxt, prev = _forward(links), _backward(links)
    before, after = prev.get(section_id), nxt.get(section_id)
    if before is None and after is None and section_id != start:
        return Rewire(noop=f"{section_id} is not in the chain")

    unlink = tuple(pair for pair in ((before, section_id), (section_id, after)) if None not in pair)
    if before is not None and after is not None:
        return Rewire(unlink=unlink, link=((before, after),))
    if before is None:
        # It was the head; the next section becomes one. `after` may be None,
        # which correctly empties the chain and clears the start.
        return Rewire(unlink=unlink, start=after, sets_start=True)
    return Rewire(unlink=unlink)


def move_plan(
    links: frozenset[Link], start: str | None, section_id: str, after: str | None
) -> Rewire:
    """Take `section_id` out of its place and put it back after `after`.

    Composed from `remove_plan` and `insert_plan` against the POST-REMOVAL
    chain, rather than reasoning about both positions at once. Written the
    direct way, moving a section to just after its own neighbour produces
    pointer pairs that cancel, and the two that survive corrupt the order.
    """
    if section_id == after:
        return Rewire(noop=f"{section_id} cannot follow itself")
    taken = remove_plan(links, start, section_id)
    if taken.noop:
        return taken

    after_removal = frozenset(set(links) - set(taken.unlink) | set(taken.link))
    head = taken.start if taken.sets_start else start
    remaining = {a for a, _ in after_removal} | {b for _, b in after_removal}
    if head is not None:
        remaining.add(head)
    if after is not None and after not in remaining:
        return Rewire(noop=f"{after} is not in the chain")

    put = insert_plan(after_removal, head, section_id, after)
    if put.noop:
        return put

    unlink = tuple(dict.fromkeys(taken.unlink + put.unlink))
    link = tuple(dict.fromkeys(taken.link + put.link))
    # A pair both removed and re-added is not a change, and emitting it would
    # make an apply that deletes then recreates the same edge -- churn in the
    # log and a needless write.
    both = set(unlink) & set(link)
    # The later plan wins: `put` ran against the chain `taken` had already left
    # behind, so its view of the head is the current one.
    latest = put if put.sets_start else taken
    return Rewire(
        unlink=tuple(p for p in unlink if p not in both),
        link=tuple(p for p in link if p not in both),
        start=latest.start if latest.sets_start else None,
        sets_start=latest.sets_start and latest.start != start,
    )


def position_for(spine_order: list[str], in_chain: frozenset[str], section_id: str) -> str | None:
    """Where an unplaced canon section goes: after its nearest in-chain
    predecessor in the BOOK's order, or at the head if it has none.

    Used by unskip and by reconciliation, and deliberately the same rule for
    both. It never moves anything the DM placed -- it only decides where a
    section the DM has expressed no opinion about belongs.
    """
    if section_id not in spine_order:
        return None
    for earlier in reversed(spine_order[: spine_order.index(section_id)]):
        if earlier in in_chain:
            return earlier
    return None


def adjacent_homebrew(
    links: frozenset[Link], section_id: str, bound: int = 3
) -> tuple[tuple[str, ...], tuple[str, ...], int]:
    """Campaign sections chained immediately around `section_id`.

    Returns `(before, after, cut)` -- `before` nearest-first.

    THE RIDE-ALONG, AND WHY IT IS NOT A SEARCH. A scene the DM chained into the
    voyage may share no vocabulary at all with "what happens on the way to the
    prison", so no Lucene score and no occurrence count can find it. Its
    relevance is POSITIONAL, and the chain records the position as a fact the
    DM asserted. So it is fetched by walking, not ranked.

    BOTH DIRECTIONS, because a scene chained just before Revel's End is as
    adjacent to it as one chained just after Trek. CONTIGUOUS CAMPAIGN SECTIONS
    ONLY, STOPPING AT THE FIRST CANON ONE: walking past a canon section would
    drag in the neighbourhood of something retrieval did not retrieve, and canon
    does not need riding along -- it is reachable on its own words. Homebrew two
    canon sections away rides with ITS neighbour when that one is retrieved.

    `cut` is what the bound dropped, for the render line. Never silent.
    """
    nxt, prev = _forward(links), _backward(links)
    cut = 0

    def collect(step: dict[str, str]) -> tuple[str, ...]:
        nonlocal cut
        found: list[str] = []
        seen: set[str] = {section_id}
        current = step.get(section_id)
        while current is not None and is_campaign_id(current) and current not in seen:
            if len(found) >= bound:
                cut += 1
                current = step.get(current)
                continue
            found.append(current)
            seen.add(current)
            current = step.get(current)
        return tuple(found)

    return collect(prev), collect(nxt), cut
