"""What a conversation is holding: nodes, edges and passages, with provenance.

THE TRANSCRIPT IS NOT THE MEMORY. A DM runs one chat for a session or a
campaign, and carrying more dialogue is the wrong way to remember: it is too
small to reach session 3 from session 7, and enlarging it re-sends old prose on
every turn in the hope the answer is somewhere in it. What carries instead is
this -- what the conversation is ABOUT, as graph entities with ids -- and the
campaign plane, which the graph already holds.

So a pronoun needs no resolver. "What makes him special" works because Rictavio
is a node here with an id, not because the previous message is still in view.
Before this existed, that follow-up resolved nothing, searched Lucene for
`him, makes, special`, and returned the heading `Special Events` eight times
from eight chapters along with 93 relationships harvested from them.

WHAT THIS IS NOT: a cache that saves tokens. The model has no memory between
calls, so a section a later turn needs is re-sent whether or not this recorded
having read it. Measured on a real turn, passage prose is 82% of the input and
relationship lines are 3%; the floor is the book, and no bookkeeping on this
side lowers it. This is a correctness and continuity design.

EVICTION IS REQUIRED, NOT OPTIONAL. With the transcript gone, this is the only
thing between a long campaign and an unbounded working set.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable
from dataclasses import dataclass, field, replace

#: How something got here. Ordered by how much a reader should trust it.
SEEDED = "seeded"  # deterministic retrieval resolved a name in the question
EXPANDED = "expanded"  # the graph agent went and fetched it
NAMED = "named"  # an answer actually used it

#: Characters per token, for the default estimator. English prose runs about
#: four; the estimate only has to be stable, because it is compared against a
#: budget that was itself chosen by looking at these numbers.
_CHARS_PER_TOKEN = 4


def _estimate(text: str) -> int:
    return max(1, len(text) // _CHARS_PER_TOKEN)


@dataclass(frozen=True)
class Held:
    """One entity the conversation is holding.

    `turn` is when it was last TOUCHED, not when it arrived. A node the
    conversation keeps returning to stays; one mentioned once and left behind
    ages out. That is the whole of the recency rule, and it is a field rather
    than a computation so that eviction cannot disagree with rendering about
    which is older.
    """

    id: str
    name: str
    labels: tuple[str, ...] = ()
    how: str = SEEDED
    turn: int = 0

    @property
    def line(self) -> str:
        kinds = "/".join(self.labels) if self.labels else "?"
        return f"{self.name} ({kinds})"


@dataclass(frozen=True)
class HeldEdge:
    """One relationship, carrying the status it had in the graph.

    `status` travels because a proposed edge is a guess -- roughly a third of
    them are false -- and an edge that arrived here without its status would be
    a guess wearing a fact's clothes. Nothing in this module is allowed to drop
    it.
    """

    source: str
    rel_type: str
    target: str
    status: str
    how: str = SEEDED
    turn: int = 0

    @property
    def key(self) -> tuple[str, str, str]:
        return (self.source, self.rel_type, self.target)

    @property
    def line(self) -> str:
        return f"{self.source} -{self.rel_type}-> {self.target}"


@dataclass
class Subgraph:
    """The conversation's working view of the canon graph.

    Mutable, unlike almost everything else in this codebase, because it IS the
    conversation's state -- a frozen version would mean rebuilding it every
    turn, which is the stateless design this replaces.
    """

    nodes: dict[str, Held] = field(default_factory=dict)
    edges: dict[tuple[str, str, str], HeldEdge] = field(default_factory=dict)
    #: Section ids already read, and on which turn. The TEXT is not held: it
    #: has to be re-sent from retrieval anyway, and a second copy of the prose
    #: is the 35,383-character duplication `WriteMention` exists to refuse.
    passages: dict[str, int] = field(default_factory=dict)
    turn: int = 0

    # -- building ----------------------------------------------------------

    def touch_node(
        self, id: str, name: str, labels: Iterable[str] = (), how: str = SEEDED
    ) -> None:
        """Add an entity, or bring an existing one forward to this turn.

        An entity already held keeps its ORIGINAL `how`. Something that was
        seeded by a resolved name does not become a guess because a later turn
        happened to expand into it, and the reverse would overstate it.
        """
        existing = self.nodes.get(id)
        if existing is None:
            self.nodes[id] = Held(id, name, tuple(labels), how, self.turn)
        else:
            self.nodes[id] = replace(existing, turn=self.turn)

    def touch_edge(
        self, source: str, rel_type: str, target: str, status: str, how: str = SEEDED
    ) -> None:
        edge = HeldEdge(source, rel_type, target, status, how, self.turn)
        existing = self.edges.get(edge.key)
        self.edges[edge.key] = (
            edge if existing is None else replace(existing, turn=self.turn)
        )

    def touch_passage(self, section_id: str) -> None:
        self.passages[section_id] = self.turn

    def already_read(self, section_id: str) -> bool:
        """Has this conversation seen this section before?

        Not used to skip sending it -- it must be sent again, the model has no
        memory -- but to tell a reader, and a later ranking, that this is
        ground already covered.
        """
        return section_id in self.passages

    # -- what a follow-up resolves through ---------------------------------

    def subjects(self, limit: int = 4) -> list[Held]:
        """What the conversation is about, most recently touched first.

        This is what a question naming nothing resolves through, and the reason
        the follow-up problem needs no pronoun rule: the entity is already here
        with an id.

        Ties broken by name so two nodes touched on the same turn come back in
        a stable order rather than a dict's.
        """
        return sorted(self.nodes.values(), key=lambda h: (-h.turn, h.name))[:limit]

    # -- keeping it bounded ------------------------------------------------

    def begin_turn(self) -> int:
        """Start a turn. Returns how many stale name-drops were expired.

        A method rather than `subgraph.turn += 1` at the call site so the
        expiry cannot be forgotten: the two belong together, because what
        expires is defined entirely in terms of the turn that just began.
        """
        self.turn += 1
        return self.expire()

    def expire(self) -> int:
        """Drop the name-drops the following turn did not pick up.

        `note_named` holds every recorded name an ANSWER used, which is what
        makes "who owns the tavern" -> "describe it" work: the question
        resolves nothing, and the tavern is only in the conversation because
        the answer said so. But that is a bet on the NEXT question, and once
        the next question has come and gone without touching it, the bet is
        settled and lost. Nothing checked, so it stayed until the token budget
        happened to evict it by age.

        Measured on a three-turn session, the working set for "Who owns the
        Blood of the Vine Tavern?" was the tavern plus SEVEN nodes that were
        all `named` residue from the previous answer's prose -- Ireena still
        carrying 22 relationships into a question about a pub. Every one of
        them was rendered into the prompt.

        One turn of grace, exactly: a node named on turn N survives turn N+1,
        which is the case this mechanism exists for, and goes on N+2.

        The most recent subject is never expired, for the reason `evict` gives
        at more length -- an empty subgraph is total amnesia, and that is never
        the better trade.
        """
        subject = self.subjects(limit=1)
        pinned = {subject[0].id} if subject else set()
        doomed = [
            held
            for held in self.nodes.values()
            if held.how == NAMED and held.turn < self.turn - 1 and held.id not in pinned
        ]
        return sum(self._drop_node(held) for held in doomed)

    def _drop_node(self, held: Held) -> int:
        """Remove an entity and the edges that mentioned it. Returns the count.

        An edge whose endpoint is gone would render as a dangling claim about a
        name nothing else explains, so the two can never be separated.
        """
        del self.nodes[held.id]
        dropped = 1
        for key in [
            k for k, e in self.edges.items() if held.name in (e.source, e.target)
        ]:
            del self.edges[key]
            dropped += 1
        return dropped

    def _is_residue(self, item: Held | HeldEdge) -> bool:
        """A name an answer used, that nothing here explains.

        The weakest thing the working set can hold: it contributes one bare
        `Rahadin (NPC)` line to the prompt, says nothing the answer did not
        already say, and is not evidence the conversation is ABOUT it.
        """
        return (
            isinstance(item, Held)
            and item.how == NAMED
            and not any(
                item.name in (e.source, e.target) for e in self.edges.values()
            )
        )

    def evict(self, budget: int, estimate: Callable[[str], int] = _estimate) -> int:
        """Drop the weakest items until the rendering fits `budget`.

        Returns how many were dropped.

        RESIDUE FIRST, THEN OLDEST-TOUCHED, with two things pinned.

        Age alone got this backwards. On a real session Strahd survived as a
        bare `Strahd von Zarovich (LORE/NPC)` line with ZERO edges, because he
        had been re-named on a later turn, while the 51 relationships that
        actually said something about him were evicted for being older. The
        structure is the valuable part and it went first. So an edgeless
        name-drop is spent before anything else, whatever its turn -- see
        `_is_residue`.

        Anything touched on the CURRENT turn: evicting what the conversation is
        talking about right now to make room for what it is talking about right
        now is a loop.

        And THE MOST RECENT SUBJECT, always, whatever the budget. A subgraph
        evicted to empty is a conversation with total amnesia -- it is the only
        memory now that the transcript is gone -- and that is never a better
        trade than being a little over budget. Without this, a tight budget
        after an unanchored turn dropped the one entity the conversation was
        about.

        An evicted node is not a deleted one. The graph still has it and the
        graph agent can fetch it again; what is lost is only that this
        conversation was holding it.
        """
        dropped = 0
        while estimate(self.render()) > budget:
            subject = self.subjects(limit=1)
            pinned = {subject[0].id} if subject else set()
            stale = [
                held
                for held in self.nodes.values()
                if held.turn < self.turn and held.id not in pinned
            ] + [edge for edge in self.edges.values() if edge.turn < self.turn]
            if not stale:
                return dropped
            weakest = min(
                stale, key=lambda item: (0 if self._is_residue(item) else 1, item.turn)
            )
            if isinstance(weakest, Held):
                dropped += self._drop_node(weakest)
            else:
                del self.edges[weakest.key]
                dropped += 1
        return dropped

    def as_dict(self) -> dict:
        """The working set, for a reader rather than for the model.

        Carries `how` and `turn` on every item, which `render` deliberately
        does not: the model needs to know WHAT the conversation is about, and a
        person watching it needs to know how each thing got there and when. A
        node that arrived because an answer happened to name it is weaker
        evidence than one a question resolved, and a panel that showed them
        alike would hide the difference the whole `how` field exists to record.
        """
        return {
            "nodes": [
                {
                    "id": held.id,
                    "name": held.name,
                    "labels": list(held.labels),
                    "how": held.how,
                    "turn": held.turn,
                }
                for held in self.subjects(limit=len(self.nodes))
            ],
            "edges": [
                {
                    "source": edge.source,
                    "rel_type": edge.rel_type,
                    "target": edge.target,
                    "status": edge.status,
                    "how": edge.how,
                    "turn": edge.turn,
                }
                for edge in sorted(self.edges.values(), key=lambda e: e.key)
            ],
            "passages": len(self.passages),
            "turn": self.turn,
        }

    # -- what survives a restart -------------------------------------------

    def snapshot(self) -> dict:
        """The whole state, round-trippable. NOT `as_dict`.

        `as_dict` is a VIEW, for the panel a DM watches: it reports `passages`
        as a count, because a reader wants to know how much has been read and
        not which ids. Restoring from it would silently drop the read-passage
        set and the conversation would re-fetch prose it had already seen.

        Two methods rather than one because they answer different questions,
        and the failure of merging them is asymmetric: a view that carries too
        much is noise, a restore that carries too little is amnesia wearing the
        face of a working session.
        """
        return {
            "nodes": [
                {"id": h.id, "name": h.name, "labels": list(h.labels),
                 "how": h.how, "turn": h.turn}
                for h in self.nodes.values()
            ],
            "edges": [
                {"source": e.source, "rel_type": e.rel_type, "target": e.target,
                 "status": e.status, "how": e.how, "turn": e.turn}
                for e in self.edges.values()
            ],
            "passages": dict(self.passages),
            "turn": self.turn,
        }

    @classmethod
    def restore(cls, payload: dict | None) -> "Subgraph":
        """A subgraph from a `snapshot`, or an empty one.

        TOLERANT OF A PARTIAL PAYLOAD, deliberately. This reads state written by
        an older build, and a restore that raised on a missing key would turn a
        schema addition into every reader losing their thread. A field that is
        not there takes its default; the conversation continues one field
        poorer rather than not at all.
        """
        found = cls()
        if not payload:
            return found
        for node in payload.get("nodes") or ():
            if not node.get("id"):
                continue
            found.nodes[node["id"]] = Held(
                id=node["id"], name=node.get("name", ""),
                labels=tuple(node.get("labels") or ()),
                how=node.get("how", SEEDED), turn=int(node.get("turn", 0)),
            )
        for edge in payload.get("edges") or ():
            if not (edge.get("source") and edge.get("target")):
                continue
            held = HeldEdge(
                source=edge["source"], rel_type=edge.get("rel_type", ""),
                target=edge["target"], status=edge.get("status", ""),
                how=edge.get("how", SEEDED), turn=int(edge.get("turn", 0)),
            )
            found.edges[held.key] = held
        found.passages = {
            k: int(v) for k, v in (payload.get("passages") or {}).items()
        }
        found.turn = int(payload.get("turn", 0))
        return found

    # -- what the model sees -----------------------------------------------

    def render(self, include_proposed: bool = True) -> str:
        """A compact summary. Empty string when the conversation holds nothing.

        `include_proposed` is applied HERE rather than at seeding, for the
        reason `canon_context.apply` gives: dropping the guesses is about what
        the model may read, not about what the conversation holds. The subgraph
        goes on knowing them, so turning the knob back on needs no re-fetch.

        Not honouring it was a real regression, caught by the test that asserts
        `include_proposed: False` keeps `Arik -SEEKS-> Ireena` out of the
        prompt: the canon block dropped it and the subgraph put it back.

        Deliberately NOT the passages' prose. This says what the conversation
        is about; retrieval says what the book says about it, and duplicating
        the second here would double the largest part of the input for no gain.

        Edges are split by status under the same two headings
        `canon_context` uses, because a guess must not be readable as a fact
        anywhere it appears, and this is another place it appears.
        """
        if not self.nodes:
            return ""

        lines = ["IN THIS CONVERSATION so far:"]
        lines += [f"  {held.line}" for held in self.subjects(limit=len(self.nodes))]

        derived = [e for e in self.edges.values() if e.status == "accepted"]
        guessed = (
            [e for e in self.edges.values() if e.status != "accepted"]
            if include_proposed
            else []
        )
        for heading, group in (
            ("  Established relationships:", derived),
            ("  Unverified relationships (about a third are wrong):", guessed),
        ):
            if group:
                lines.append(heading)
                lines += [f"    {edge.line}" for edge in sorted(group, key=lambda e: e.key)]
        return "\n".join(lines)


def seed(graph: Subgraph, retrieval, *, status_of=None) -> None:
    """Fold one turn's deterministic retrieval into the subgraph.

    Kept a module function rather than a method so `Subgraph` itself imports
    nothing and stays testable without a `Retrieval` -- the same reason
    `plan_write` is pure and its caller reads the seeds.

    ONLY THE ANCHORS BECOME NODES, AND EDGES ONLY WHEN THERE ARE ANCHORS. A
    passage names dozens of entities incidentally: the follow-up that motivated
    all this pulled 93 relationships out of eight junk sections. Admitting
    every entity a returned section mentions would fill the working set with
    things the conversation never discussed.

    The edge half of that rule was missing for one commit and the live two-turn
    check found it. On the graph path `EDGES` is queried on the RESOLVED
    anchors, so its edges are about what the question named. On the text path
    they come from `ENTITIES_IN_SECTIONS` -- whatever Lucene happened to
    return -- and are incidental to a guess. Seeding those anyway put 93
    turn-two edges into the subgraph, where being current-turn PINNED them
    against eviction, and eviction then dropped Rictavio to make room. The junk
    evicted the subject of the conversation.

    Direction is read the way `canon_context._edge_line` reads it, because
    `EDGES` returns both directions and reversal is one of the extractor's
    measured failure modes. Two places writing that arrow differently would put
    two different claims in front of a reader.
    """
    for anchor in retrieval.anchors:
        graph.touch_node(anchor.entity_id, anchor.name, anchor.labels, SEEDED)
    for passage in retrieval.passages:
        graph.touch_passage(passage.section_id)
    if not retrieval.anchors:
        return
    for edges, status in ((retrieval.accepted, "accepted"), (retrieval.proposed, "proposed")):
        for edge in edges:
            source = edge.get("entity", "?")
            target = edge.get("other", "?")
            if edge.get("direction") == "in":
                source, target = target, source
            graph.touch_edge(source, edge.get("relationship", "?"), target,
                             edge.get("status", status))


def note_named(graph: Subgraph, answer: str, resolver) -> None:
    """Record the entities an ANSWER named. The third way in, and the one the
    other two cannot cover.

    Asked "who owns the tavern", retrieval anchors NOTHING -- `tavern` is a
    common noun and refused, and the question never spells out "Blood of the
    Vine Tavern". The text path answers it correctly anyway. Then "describe it"
    has nothing to resolve through and searches Lucene for `describe`, which
    returns sections headed `Details`, `Age`, `Light`, `Humor` and `The
    Unknown`, and the model says the canon does not cover it.

    The conversation was demonstrably about the tavern: THE ANSWER SAID SO. So
    the answer is scanned for recorded names, with the same matcher retrieval
    uses on a question -- whole-word, apostrophe-folded, and refusing the
    common nouns that `anchorable_forms` refuses. Deterministic, no model, and
    it costs one pass over about two hundred tokens of prose.

    `resolver` is injected rather than imported so this stays testable without
    a database, the same reason `plan_write` takes its seeds.
    """
    for entity_id, name, labels in resolver(answer):
        graph.touch_node(entity_id, name, labels, how=NAMED)
