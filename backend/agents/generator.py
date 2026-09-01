"""Generate a quest, NPC, monster or scene, keeping each source distinguishable.

THE SPLIT IS THE PRODUCT. Anything a model writes about Barovia will read like
the book -- that is what it is good at -- and a DM who cannot tell which half
came from the adventure will eventually contradict the adventure at the table,
or worse, treat an invented detail as a fact the players have already been told.
So the model is required to return two lists: what it took from the supplied
passages, each citing one, and what it made up.

A THIRD LIST WHEN THERE IS A THIRD SOURCE. Once a conversation can hand context
to this -- the entities a table is holding, a remark the DM made -- there are
three origins and two buckets, and the model must file the DM's own words as
either the book's or its own. Both are false. So `from_context` is required
exactly when context was supplied, and not otherwise: a field that is usually
empty is one a model learns to leave empty on the occasion it matters.

That requirement is enforced at the SCHEMA level rather than asked for in prose,
because "please distinguish" is advice and a required field is a contract. A
response missing either list fails to parse and is reported as a failure rather
than passed along looking complete.

WHAT THIS DOES NOT DO. It does not check that a claimed citation supports the
claim. The model can attribute an invented detail to passage [2] and nothing
here will catch it; the citation is a pointer for a human to check, not a proof.
Saying so plainly is worth more than a verification step that only appears to
work -- this project has already spent four separate attempts failing to
automate exactly that kind of judgment.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any

from backend.agents import canon_context
from backend.campaign import homebrew, ontology
from backend.canon.retrieval import Retrieval
from backend.core.pricing import Usage, estimate

#: What can be generated. A closed set, checked before anything reaches a model:
#: an unknown kind would otherwise become an unconstrained prompt.
KINDS = ("quest", "npc", "monster", "scene", "encounter")

#: What a CLUSTER may declare as a member. A separate closed set from `KINDS`,
#: because these are different questions: `KINDS` is what a DM may ask for on
#: its own, `ELEMENT_KINDS` is what a generation may say it contains. A
#: location, an item and a piece of lore are worth minting when a quest names
#: them and are not worth a generator of their own -- nobody asks the chat for
#: a bare LORE node.
#:
#: `quest` IS HERE BECAUSE A SCENE OFTEN CONTAINS ONE, and leaving it out was
#: the largest single cause of a declared edge being thrown away. A scene whose
#: point is "someone offers the party a job" holds a job; without a QUEST to
#: mint, `GAVE_QUEST` had nothing to point at, and the model aimed it at the
#: nearest NPC or ITEM every time -- three of nine type failures in a
#: ten-subject run. Narrowing the vocabulary hid that; this is the cause.
#:
#: `scene` IS STILL NOT HERE. A scene inside a scene is a structural claim
#: about the running order, and the running order is a linked list a DM
#: arranges -- not something a generation gets to assert about itself.
ELEMENT_KINDS = (
    "npc", "monster", "location", "item", "lore", "quest", "faction",
    # A SCENE AND AN ENCOUNTER ARE THINGS A QUEST CONTAINS. Without them the
    # annotate pass dropped five candidates from one ambush as "element kind
    # 'scene' not offered" -- the model reading the prose correctly and being
    # told it may not say so. They mint as STUBS with no position, which is the
    # honest shape: an entity is a thing, and where it is played is a separate
    # decision the running order makes.
    "scene", "encounter",
)

#: What each element kind MEANS, for the pass that lists them. The kinds
#: reached the annotate prompt as a bare row of words -- `scene|encounter` and
#: nothing about when either applies -- so a passage with a boarding action in
#: it produced four scenes and no encounter. A name is not a definition.
#:
#: Only the two that are easy to confuse are glossed. `npc` and `item` need no
#: help; a scene and an encounter are both episodes and the difference between
#: them is whether somebody is fighting.
ELEMENT_GLOSS = """
  scene      -- an episode that happens at a point in the adventure
  encounter  -- an episode that is a FIGHT: name it when the text has one,
                with the opposition as its own elements beside it
  faction    -- a group that acts as one: a crew, a clan, a guild
"""

#: The kinds line the prompts print, built from `ELEMENT_KINDS` rather than
#: written out beside it. The two had already drifted: the annotate prompt
#: still offered `npc|monster|location|item|lore` after `quest` and `faction`
#: joined, so a faction only ever arrived because the model ignored the list it
#: was given, and a scene was refused for obeying it.
_KINDS_LINE = "|".join(ELEMENT_KINDS)

SHAPES = {
    "quest": "a quest hook: who gives it, what it asks, what stands in the way, "
             "and what completing it changes",
    "npc": "a non-player character: name, what they do, how they behave, what "
           "they want, and one thing they are hiding",
    "monster": "a creature encounter: what it is, where it is met, how it "
               "fights, and what a party can learn from it",
    # ADDED FOR THE CASE THE OTHER THREE CANNOT HOLD: an episode inserted into
    # a published adventure's sequence -- a sea battle on the voyage to the
    # prison. It is not a quest (nobody gives it), not an NPC, and not a
    # monster; what defines it is WHERE IN THE RUNNING ORDER it happens. `KINDS`
    # is a closed set precisely so an addition is a decision, and this is one.
    # WHAT IT TOUCHES OF THE BOOK'S, added on measurement. Every other kind
    # asks for something only canon can answer -- a quest for who gives it, a
    # monster for where it is met -- and a scene asked only about its own
    # shape, which a model can supply out of nothing. Over eleven runs of one
    # subject a scene cited the book 1.6 times on average and cited it not at
    # all three times; a quest over four runs never went below three. The gap
    # NAME, DO NOT DESCRIBE, added after the same measurement caught the cost.
    # Asking a scene which of the book's things it touches pushed grounding
    # from 1.2 citations to 2.7 and stopped it citing nothing -- and the first
    # two claims unsupported by ANY passage in a hundred-odd judged all
    # session came straight after, both from one scene, both describing a
    # canon place rather than naming it: "looms on a high precipice", "towers
    # pierce the clouds". Naming a thing needs no invention; saying what it
    # looks like does, and that description is what got filed under the book.
    #
    # Two failures at n=55 is not distinguishable from noise -- the intervals
    # overlap and the gate still passes -- so this is a cheap hedge against a
    # plausible mechanism rather than a fix for a proven regression.
    "scene": "an episode that happens at a point in the adventure: what "
             "occurs, which of the book's people, places or things it touches "
             "-- NAME them, do not describe them, since what they are like is "
             "the book's to say -- where it interrupts the journey or the plan, "
             "who appears, how it can play out, and what it changes afterwards",
    # A SCENE SAYS WHAT HAPPENS; AN ENCOUNTER SAYS WHO YOU ARE FIGHTING. Asked
    # for "a cast of enemies in a table", the closest kind was `scene`, which
    # produced good prose about a fight and left the DM to pull the opposition
    # out of it by hand at the table. What a DM needs mid-combat is a roster:
    # how many of each, what each one does in the fight, and what ends it.
    #
    # The elements are the ENEMIES, so each arrives as its own entity the DM
    # reviews and stores -- which is the whole reason this is its own kind
    # rather than a phrasing of `scene`.
    "encounter": "a combat encounter, written to be RUN: the opposition as a "
                 "roster -- how many of each kind, what each does in the "
                 "fight, and which is the dangerous one -- then the terrain "
                 "and hazards that shape it, what the enemies want (which is "
                 "rarely 'fight to the death'), and what makes them break off "
                 "or surrender. Name every enemy group as an element; put "
                 "counts and battlefield behaviour in its role",
    # THE THREE BELOW EXIST TO FLESH OUT AN ELEMENT, not to be asked for cold.
    # A cluster mints a location, an item or a piece of lore as a name and a
    # role; these are the shapes for turning one of those stubs into something
    # a DM can run from. They are in `SHAPES` and NOT in `KINDS`, so the chat
    # tool never offers "generate me a lore" while `expand` can still ask for
    # exactly that.
    "location": "a place: what a party sees on arriving, who or what is "
                "there, what can be done in it, and what it connects to",
    "item": "an object: what it looks like, what it does, who wants it, and "
            "what carrying it costs or risks",
    "lore": "a piece of lore: what is believed, who tells it, how much of it "
            "is true, and what it explains about the world",
    # ADDED BECAUSE A GROUP HAD NOWHERE TO GO. Every crew, clan and guild a
    # generation named was minted `npc`, being the closest thing on offer --
    # and the type table says `A MEMBER_OF B` needs B to be a FACTION, so no
    # campaign group could ever be one. "Captain Saltmarrow leads the Corsair
    # Crew" had no writable form at all.
    "faction": "a group that acts as one: who belongs to it, what it wants, "
               "who leads it, and how it treats outsiders",
}

#: RULE 4 IS THERE BECAUSE PROSE THAT NAMES NOTHING CONNECTS TO NOTHING.
#:
#: The mention scan is how a generation joins the rest of the campaign, and it
#: reads the words. A bio of Captain Saltmarrow that says she "commands her
#: ship" and expects "loyalty from her crew" names neither The Red Barge nor
#: the Corsair Crew, both of which exist in the graph -- so the COMMANDS edge
#: the sentence plainly asserts can never be read back out of it. Measured on
#: eight campaign sections: two of the three with real prose named nothing at
#: all, one of them across 1,967 characters of "the barge", "the crew", "the
#: characters".
#:
#: It is a writing instruction with a graph reason, which is why it sits with
#: the provenance rules rather than in the shape gloss.
_INSTRUCTIONS = """You generate material for a Dungeon Master running {book}.

Generate {shape}.

Subject: {subject}

RULES, and the second is the one that matters:

1. Use the CANON passages above. They are what the adventure actually says.
2. SEPARATE what you took from canon from what you invented. Every entry in
   `from_canon` must cite the passage it came from, like [1], and must be
   something that passage actually states. Everything else -- every name, motive,
   and detail you supplied -- goes in `invented`. A DM will act on this at a
   table, and cannot afford to mistake your invention for the book's text.
3. If the passages are thin or absent, invent more and say so by putting more in
   `invented`. Do not pad `from_canon` to look better sourced.
4. NAME THINGS BY THEIR NAMES, in `body`, on first reference. If the material
   involves a person, place, ship, or group that HAS a name -- one from the
   passages above, one handed to you, or one you invented and listed -- write
   that name. Not "the captain", "her ship", "the crew". Afterwards pronouns
   are fine.{context_rule}{cluster_rule}

Return ONLY JSON, of this shape:

{{"title": "...",
  "body": "the generated material, written for a DM to read aloud or run from",
  "from_canon": [{{"claim": "what the book establishes", "cite": "[1]"}}],
  "invented": ["each detail you supplied"]{context_field}{cluster_field}}}"""

#: Appended to the rules ONLY when a conversation handed context over.
#:
#: A THIRD SOURCE NEEDS A THIRD LIST. Without it the model has two buckets for
#: three origins and must file the DM's own words as either the book's or its
#: own. Both are false, and the second is the worse of the two: it reports a
#: fact the table established as something a model made up.
_CONTEXT_RULE = """
{n}. The CONVERSATION block is a THIRD source and is neither of the first two.
   Anything you take from it goes in `from_context`. It is not the book, so it
   may not go in `from_canon`; it is not yours, so it may not go in `invented`."""

_CONTEXT_FIELD = """,
  "from_context": ["each detail taken from the conversation"]"""


def vocabulary_gloss(root_kind: str = "") -> str:
    """The writable relationships, each with what it MAY connect and what it means.

    BUILT FROM THE TABLE THAT JUDGES IT. `RELATIONSHIP_DOMAIN_RANGE` is what
    `check_edges` uses to decide whether an edge is type-possible, so a model
    instructed from anything else is being graded on a rubric it was not shown.
    The first version of this prompt listed bare type names and 42% of declared
    edges came back type-impossible -- a LOCATION that THREATENS, a casino
    LOCATED_IN a cashier -- which measured the instruction, not the model.

    Derived, never written down: adding a relationship type or widening its
    domain reaches the prompt and the checker together and cannot leave them
    disagreeing.
    """
    from backend.canon.constraints import RELATIONSHIP_DOMAIN_RANGE
    from backend.graph.schema import RELATIONSHIP_GLOSS, RelationshipType

    lines = []
    for name in homebrew_vocabulary(root_kind):
        pair = RELATIONSHIP_DOMAIN_RANGE.get(name)
        gloss = RELATIONSHIP_GLOSS.get(RelationshipType(name), "")
        # A type with no declared domain/range is unconstrained rather than
        # forbidden; say "any" instead of implying a restriction that is not
        # there.
        if pair:
            domain = "|".join(sorted(t.value for t in pair[0]))
            rng = "|".join(sorted(t.value for t in pair[1]))
        else:
            domain = rng = "any"
        lines.append(f"     {name}: {domain} -> {rng}   ({gloss})")
    return "\n".join(lines)


def available_types(root_kind: str = "") -> frozenset[str]:
    """The entity types an edge in this generation could possibly connect.

    Everything a cluster may MINT, plus the generation itself -- and nothing
    else, because `cluster._plan_edges` drops any edge reaching outside the
    cluster, so a type that cannot appear here cannot appear in a written edge.
    """
    from backend.campaign.homebrew import LABELS

    kinds = {LABELS[k] for k in ELEMENT_KINDS if k in LABELS}
    if root_kind in LABELS:
        kinds.add(LABELS[root_kind])
    return frozenset(kinds)


def homebrew_vocabulary(root_kind: str = "") -> tuple[str, ...]:
    """The relationship types a generation may declare between its elements.

    DERIVED FROM `LAYER_MAP`, exactly as `extract.layer_vocabulary` derives the
    extractor's, so one table feeds both pipelines and adding a type cannot
    leave either silently unaware of it. The types mapped to NO layer are the
    ones excluded, and they are excluded correctly without a hand-written
    denylist: `ATTENDED`, `PLAYS_AS`, `HAS_CLASS` and their kind are session
    bookkeeping and runtime state, not the authored world a DM invents.

    THEN NARROWED TO WHAT THIS GENERATION COULD SATISFY, which is the larger
    filter and was missing. `ELEMENT_KINDS` cannot mint a QUEST, so a scene's
    cluster holds no node a `GAVE_QUEST` could ever point at -- and the model,
    offered the relationship and asked to use it, aimed at the nearest NPC or
    ITEM every time. Three of nine type failures in a ten-subject run were that
    one shape: `Alda Arkin GAVE_QUEST Rival Crew`, `Alenka GAVE_QUEST Fortune
    Reading`. Not a model getting it wrong so much as a prompt asking for
    something the reply could not contain.

    A `quest` generation still gets `GAVE_QUEST`, because its root IS a QUEST.
    The vocabulary is a function of what is on the table.
    """
    from backend.canon.constraints import RELATIONSHIP_DOMAIN_RANGE
    from backend.graph.schema import LAYER_MAP

    layered = sorted(r.value for r, layer in LAYER_MAP.items() if layer is not None)
    if not root_kind:
        return tuple(layered)

    here = available_types(root_kind)
    usable = []
    for name in layered:
        pair = RELATIONSHIP_DOMAIN_RANGE.get(name)
        # No declared domain/range is unconstrained, not forbidden -- it can
        # connect anything, so it stays.
        if pair is None:
            usable.append(name)
            continue
        domain = {t.value for t in pair[0]}
        rng = {t.value for t in pair[1]}
        if domain & here and rng & here:
            usable.append(name)
    return tuple(usable)


#: Asked for only when a cluster was requested, and required exactly then --
#: `_CONTEXT_RULE`'s rule, for `_CONTEXT_RULE`'s reason: a list that is usually
#: empty is one a model learns to leave empty on the occasion it matters.
#:
#: THE AUTHOR DECLARES, RATHER THAN A READER REDISCOVERING. A generation that
#: writes "Captain Saltmarrow commands the Red Barge" already holds that edge;
#: asking a second model to find it again in the prose is a lossy round-trip
#: with nothing gained. Book extraction exists because the author is
#: unavailable. Here the author is the same call.
_CLUSTER_RULE = """
{n}. LIST WHAT THIS CONTAINS. Anything the material names that a DM would want
   as its own thing -- a place, a person, a creature, an object, a piece of
   lore, a job the party is given -- goes in `elements`, each with its OWN
   three provenance lists, split by the same rule as above. Relationships
   between them go in `edges`.
   Name an element by its `name`; name something from the CANON passages by
   the id shown beside it, and never by an id you were not shown.
   An element you would only mention in passing is scenery -- leave it out.

   IF AN EDGE NEEDS A THING, LIST THE THING. `GAVE_QUEST` needs a `quest`
   element to point at; `LOCATED_IN` needs the place. Declare it in `elements`
   first, or leave the edge out -- naming something only in the edge does not
   create it.

   AN EDGE MAY ONLY JOIN TWO THINGS ON THIS CARD -- an element you just listed,
   or the material itself by its title. An edge naming anything else, including
   a canon id, is DISCARDED. Elements are for naming what the book already has;
   edges are for what this material puts together.

   USE ONLY THESE RELATIONSHIPS, AND ONLY BETWEEN THE TYPES SHOWN. The arrow
   is `source -> target` and the direction matters: an edge whose endpoints
   are the wrong types is DISCARDED, so check the line before you write one.
{vocabulary}"""

_CLUSTER_FIELD = """,
  "elements": [{{"kind": "{kinds}", "name": "...",
                "role": "what it is here in one line",
                "from_canon": [], "invented": ["..."]}}],
  "edges": [{{"source": "...", "target": "...", "rel_type": "LOCATED_IN",
             "provenance": "canon|context|invented", "cite": "[1]"}}]"""


@dataclass(frozen=True)
class GenerationContext:
    """What a CONVERSATION contributes to a generation, made explicit.

    The generator reads the graph itself; this is the additional context the
    chat agent chose to hand over -- the entities the conversation is already
    about, and anything the DM said that is not in any book.

    PASSED AS AN ARGUMENT RATHER THAN INHERITED. `/lab/generate` builds a fresh
    agent every time so that "two identical requests return different things
    for reasons nobody could see" cannot happen, and that reason is still good.
    A conversation reaching generation as DATA keeps it: the same call with the
    same context behaves the same way twice, and the context is printed back in
    the response, so nothing reaches the model that a reader cannot see.
    """

    #: Display names of entities the conversation is holding.
    entities: tuple[str, ...] = ()
    #: What the DM said, which may be in no book at all.
    note: str = ""

    @property
    def empty(self) -> bool:
        return not self.entities and not self.note.strip()

    def render(self) -> str:
        """The block the model reads, or empty when there is nothing to say."""
        if self.empty:
            return ""
        parts = [
            "CONVERSATION — what this table was already talking about. NOT the "
            "book: some of it may be the DM's own, said at the table. Anything "
            "you take from here goes in `from_context`, never in `from_canon`."
        ]
        if self.entities:
            parts.append("Already in play: " + ", ".join(self.entities) + ".")
        if self.note.strip():
            parts.append(f"The DM adds: {self.note.strip()}")
        return "\n".join(parts)


@dataclass(frozen=True)
class Generated:
    """One generation, with its provenance split and its cost."""

    kind: str
    subject: str
    title: str
    body: str
    from_canon: tuple[dict, ...]
    invented: tuple[str, ...]
    sources: tuple[dict, ...]
    usage: dict
    cost: dict
    #: Taken from the CONVERSATION rather than from the book or from thin air.
    #: A third bucket because folding it into either existing one would be
    #: false in both directions: `from_canon` would claim the book says
    #: something it does not, and `invented` would claim the model made up
    #: something the DM actually said. The two-way split is what this module
    #: promises; a third source needs a third answer.
    #:
    #: Sits here rather than beside its two siblings only because it carries a
    #: default and they do not; read it as the third of three.
    from_context: tuple[str, ...] = ()
    #: Claims the model filed under `from_canon` that cite the DM's OWN
    #: material. A FOURTH bucket, derived and never asked for: the model sees
    #: one numbered list of passages and, once a campaign has prose of its own,
    #: that list spans both planes. It cited two of the DM's scenes as the book
    #: -- "Corsairs swarm the deck at dawn", a word that appears nowhere in
    #: either published book -- and the card printed it in green under "From
    #: the book". `homebrew.split_by_origin` re-files it by resolving each cite
    #: to the plane of the passage it points at, which is a check rather than a
    #: request the model can decline.
    from_yours: tuple[dict, ...] = ()
    #: The section this REPLACES. Set when the DM asked to change something
    #: that exists, and the reason the card stores by rewriting rather than by
    #: minting -- otherwise "build out the sea battle" leaves two sea battles.
    revises: str = ""
    #: The entity this gives its FIRST prose to, when it had only a name and a
    #: role. The card stores it by expanding rather than by minting a second.
    expands: str = ""
    #: What this generation says it contains, each with its own provenance
    #: split, and the relationships it declares between them. Empty for a
    #: single-artifact generation, which is every one that existed before
    #: clusters -- so an empty manifest is the backward-compatible case rather
    #: than a failure.
    elements: tuple[dict, ...] = ()
    edges: tuple[dict, ...] = ()
    #: Manifest entries thrown away and WHY, keyed by reason. Counted rather
    #: than dropped silently, and non-fatal: a bad element is not worth losing
    #: a generation over, and the counts are what the reliability measurement
    #: is made of.
    manifest_dropped: dict = field(default_factory=dict)
    retrieval: dict | None = None
    #: Set when the model returned something that would not parse. The raw text
    #: travels with it: a malformed response is evidence about the prompt, and
    #: discarding it leaves nothing to debug from.
    error: str = ""
    raw: str = ""

    def as_dict(self) -> dict:
        return {
            "kind": self.kind,
            "subject": self.subject,
            "title": self.title,
            "body": self.body,
            "from_canon": list(self.from_canon),
            "invented": list(self.invented),
            "from_context": list(self.from_context),
            "from_yours": list(self.from_yours),
            "revises": self.revises,
            "expands": self.expands,
            "elements": list(self.elements),
            "edges": list(self.edges),
            "manifest_dropped": dict(self.manifest_dropped),
            "sources": list(self.sources),
            "usage": self.usage,
            "cost": self.cost,
            "retrieval": self.retrieval,
            "error": self.error,
            "raw": self.raw,
        }


#: Appended when a DM asks for the same thing again with one change. Its own
#: block under its own heading, for `_CONTEXT_RULE`'s reason: the previous
#: draft is not canon, not context and not an instruction, and folding it into
#: any of those three would make the model treat a discarded attempt as
#: evidence about the world.
_REVISE = """

THE DRAFT YOU ARE REPLACING

{previous}

WHAT TO CHANGE: {note}

Write it again from the same passages, changing what was asked and as little
else as you can. This is a revision, not a second opinion -- keep the parts
nobody objected to. The provenance split is redone from scratch: a detail you
carry over is still invented if it was invented before, and still cited if the
passages still say it."""


def build_messages(
    kind: str,
    subject: str,
    retrieval: Retrieval,
    depth: canon_context.Depth,
    context: GenerationContext | None = None,
    cluster: bool = False,
    previous: str = "",
    note: str = "",
) -> list[dict]:
    """The exact messages the model will see. Pure, so a test can read them.

    `context` is what a CONVERSATION handed over, rendered as its OWN block
    under its own heading and never merged into the canon block. A DM's remark
    and the book's sentence must not reach the model looking alike -- that is
    the same rule the accepted/proposed headings follow, applied to a source
    the generator did not have until chat could call it.
    """
    # CHECKED AGAINST `SHAPES`, NOT `KINDS`. The guard exists so an unknown
    # kind cannot become an unconstrained prompt, and `SHAPES` is exactly the
    # set of shapes that exist. `KINDS` is the narrower question of what a DM
    # may ask for COLD -- `expand` fleshes out a location or a piece of lore
    # that a cluster already minted, and neither is offered as a bare request.
    if kind not in SHAPES:
        raise ValueError(f"unknown kind {kind!r}; expected one of {sorted(SHAPES)}")
    shown = canon_context.apply(retrieval, depth)
    carried = context or GenerationContext()
    system = canon_context.render(shown, max_edges=depth.max_edges, for_chat=False)
    if not carried.empty:
        system = f"{system}\n\n{carried.render()}"
    return [
        {"role": "system", "content": system},
        {
            "role": "user",
            "content": _INSTRUCTIONS.format(
                shape=SHAPES[kind],
                subject=subject,
                # The retrieval knows which book it read; this used to name one.
                book=retrieval.book_title or "this adventure",
                # Asked for only when there is a third source to ask about: a
                # required list that is always empty teaches the model to ignore
                # it, and this one has to mean something the day it is used.
                context_rule=_CONTEXT_RULE.format(n=5) if not carried.empty else "",
                context_field=_CONTEXT_FIELD if not carried.empty else "",
                # Numbered after whatever came before it, so the rules read as
                # a list rather than jumping from 3 to 4 with a gap where the
                # context rule would have been.
                cluster_rule=(
                    _CLUSTER_RULE.format(
                        n=6 if not carried.empty else 5,
                        vocabulary=vocabulary_gloss(kind),
                    )
                    if cluster
                    else ""
                ),
                cluster_field=(
                    _CLUSTER_FIELD.format(kinds=_KINDS_LINE) if cluster else ""
                ),
            )
            + (
                _REVISE.format(previous=previous.strip(), note=note.strip())
                if previous.strip() and note.strip()
                else ""
            ),
        },
    ]


def _first_object(text: str) -> tuple[dict, str]:
    """The first complete JSON object in a response, or a reason.

    TOLERANT OF A FENCE, because models wrap JSON in one often enough that
    failing on it would report a prompt problem as a model problem.

    AND TOLERANT OF WHAT COMES AFTER, which is new and was learned from a stat
    block: asked for one, the model returned its JSON and then went on to lay
    the block out in markdown underneath, and `json.loads` on the whole string
    failed with "Extra data: line 1 column 1867". The object was complete and
    correct; the draft was thrown away over what followed it.

    Nothing else is forgiven. Text BEFORE the object, or no object at all, is
    still a rejection -- a response missing `from_canon` or `invented` must not
    be defaulted to empty, because an empty `invented` reads as "all of this is
    from the book", the precise claim this module exists to keep honest.
    """
    cleaned = text.strip()
    if cleaned.startswith("```"):
        cleaned = cleaned.split("\n", 1)[-1]
        if cleaned.rstrip().endswith("```"):
            cleaned = cleaned.rstrip()[:-3]
    cleaned = cleaned.strip()
    try:
        data = json.loads(cleaned)
    except json.JSONDecodeError as exc:
        # `raw_decode` reads one value and reports where it stopped, which is
        # exactly the question here: was there a whole object at the front?
        try:
            data, _end = json.JSONDecoder().raw_decode(cleaned)
        except json.JSONDecodeError:
            return {}, f"response was not JSON: {exc}"
    if not isinstance(data, dict):
        return {}, "response was JSON but not an object"
    return data, ""


def parse(
    text: str, *, expect_context: bool = False, expect_cluster: bool = False
) -> tuple[dict, str]:
    """The model's JSON, or an empty result and a reason.

    Tolerant of a fenced code block, because models wrap JSON in one often
    enough that failing on it would report a prompt problem as a model problem.
    Tolerant of nothing else: a response missing `from_canon` or `invented` is
    REJECTED rather than defaulted to empty, since an empty `invented` list
    reads as "all of this is from the book" -- the precise claim this module
    exists to keep honest.
    """
    data, error = _first_object(text)
    if error:
        return {}, error
    required = ["from_canon", "invented"]
    # REQUIRED ONLY WHEN CONTEXT WAS GIVEN, so the contract stays a contract.
    # Demanding it always would make it usually-empty, and a field that is
    # normally empty is one a model learns to leave empty on the occasion it
    # matters -- which is the whole reason `invented` is required rather than
    # requested.
    if expect_context:
        required.append("from_context")
    # STRUCTURE IS FATAL, ENTRIES ARE COUNTED. A response with no `elements`
    # key at all did not follow the contract and is rejected like a missing
    # `invented`; a single malformed element inside it is dropped and tallied,
    # because losing a whole generation over one bad line would cost more than
    # it saves and would hide the very counts the measurement needs.
    if expect_cluster:
        required.extend(("elements", "edges"))
    for field_name in required:
        if field_name not in data:
            why = (
                "so what it contains is undeclared"
                if field_name in ("elements", "edges")
                else "so its sources are not separated"
            )
            return {}, f"response omitted {field_name!r}, {why}"
    return data, ""


#: Element kinds that are POSITIONS in the running order, mapped onto the
#: levels the ontology reasons about. The rest -- an npc, an item -- are things
#: rather than places in a sequence, and nothing contains them in this sense.
_AS_LEVEL = {"scene": ontology.SCENE, "encounter": ontology.ENCOUNTER}


def kind_of(entry: dict) -> str:
    """The kind an element claims, folded. `""` when it claims none."""
    return str(entry.get("kind") or "").strip().casefold()


def _may_not_contain(parent_kind: str, child_kind: str) -> str:
    """Why this material may not hold this element, or `""`.

    ONLY BETWEEN TWO EPISODES. A quest is not a level -- it spans an adventure
    rather than happening at a point in one -- so it may name whatever it
    involves, and an npc is a thing rather than a position. The question only
    has an answer when both sides sit in the running order.
    """
    parent, child = _AS_LEVEL.get(parent_kind, ""), _AS_LEVEL.get(child_kind, "")
    if not parent or not child:
        return ""
    return ontology.refuse(parent, child)


def sift_manifest(
    data: dict, subject: str = "", material_kind: str = ""
) -> tuple[tuple[dict, ...], tuple[dict, ...], dict]:
    """Keep the manifest entries that are usable; count the rest by reason.

    Returns `(elements, edges, dropped)`. Pure and separate from `parse` so the
    rules can be read and tested without a model, and so the counts are
    available to the reliability measurement rather than buried in a log.

    NOTHING HERE INVENTS A CORRECTION. An element with an unknown kind is
    dropped, not coerced to the nearest one; an edge naming a type outside the
    vocabulary is dropped, not mapped to something similar. Guessing what a
    model meant is how a wrong edge becomes indistinguishable from a checked
    one -- the rule the whole proposed layer exists to respect.
    """
    dropped: dict[str, int] = {}

    def drop(reason: str) -> None:
        dropped[reason] = dropped.get(reason, 0) + 1

    vocabulary = set(homebrew_vocabulary())
    elements, names = [], set()
    for entry in data.get("elements") or ():
        if not isinstance(entry, dict):
            drop("element not an object")
            continue
        name = str(entry.get("name") or "").strip()
        kind = str(entry.get("kind") or "").strip().lower()
        if not name:
            drop("element without a name")
        elif (ontology_refusal := _may_not_contain(material_kind, kind)):
            # THE ONTOLOGY DECIDES WHICH EPISODE HOLDS WHICH, and it already
            # had the answer in a sentence. An encounter listed eleven scenes
            # across four runs -- the siblings it REFERENCES rather than the
            # things it contains -- and a scene sits inside a section, never
            # inside a fight.
            drop(ontology_refusal)
        elif subject and name.strip().casefold() == subject.strip().casefold():
            # A THING DOES NOT CONTAIN ITSELF. Asked what The Corsair Ambush
            # contains, the answer is the crew, the ship and the captain --
            # not "The Corsair Ambush". Only reachable since `scene` and
            # `encounter` became element kinds, and the prompt saying so did
            # not stop it: the model listed the passage as its own first
            # element on two runs out of two. So the rule is here, where it
            # holds.
            drop("the material itself is not one of its parts")
        elif kind not in ELEMENT_KINDS:
            drop(f"element kind {kind!r} not offered")
        elif name.casefold() in names:
            # Two elements of one name in one cluster is the model saying the
            # same thing twice, not two things -- unlike two SEPARATE
            # generations a DM named alike, which `AlreadyStored` refuses.
            drop("element named twice in one cluster")
        else:
            names.add(name.casefold())
            elements.append({**entry, "name": name, "kind": kind})

    edges = []
    for entry in data.get("edges") or ():
        if not isinstance(entry, dict):
            drop("edge not an object")
            continue
        rel = str(entry.get("rel_type") or "").strip().upper()
        source = str(entry.get("source") or "").strip()
        target = str(entry.get("target") or "").strip()
        if not source or not target:
            drop("edge missing an endpoint")
        elif rel not in vocabulary:
            drop(f"relationship {rel!r} not in the writable vocabulary")
        elif source.casefold() == target.casefold():
            drop("edge points at itself")
        else:
            edges.append({**entry, "source": source, "target": target, "rel_type": rel})

    return tuple(elements), tuple(edges), dropped


_ANNOTATE = """Here is material a DM has just had written for their game.

{body}

List what it contains, so each thing can be stored separately.

RULES:

1. LIST ONLY WHAT THIS MATERIAL ADDS. If the CANON passages below already name
   something, it belongs to the book and is not yours to list -- the scene uses
   it, and using a thing is not inventing it. List a place, person, creature,
   object or piece of lore only when this text is where it first exists.
2. Something mentioned once in passing is scenery; leave it out.
2a. WHAT THE KINDS MEAN, where two of them are easy to confuse:
{kind_gloss}
2b. THE MATERIAL IS NOT ONE OF THE THINGS IT CONTAINS. Do not list the passage
   itself. Asked what The Corsair Ambush contains, the answer is the crew, the
   ship and the captain -- not "The Corsair Ambush". It became possible to get
   this wrong the moment `scene` and `encounter` were offered as kinds, and a
   thing cannot contain itself.
3. Use the names exactly as the text writes them.
4. For each thing, say what in it leans on the CANON passages below (citing
   one, like [1]) and what was invented. A new innkeeper standing in the
   book's own tavern is new, and the tavern is the citation.
5. Relationships go in `edges`. USE ONLY THESE, AND ONLY BETWEEN THE TYPES
   SHOWN. The arrow is `source -> target` and the direction matters; an edge
   whose endpoints are the wrong types is discarded, so check the line first.
{vocabulary}

{sources}

Return ONLY JSON:

{{"elements": [{{"kind": "{kinds}", "name": "...",
                "role": "what it is here, in one line",
                "from_canon": [{{"claim": "...", "cite": "[1]"}}],
                "invented": ["..."]}}],
  "edges": [{{"source": "...", "target": "...", "rel_type": "LOCATED_IN",
             "provenance": "canon|invented", "cite": "[1]"}}]}}"""


_READ_BACK = """Here is a passage from a Dungeon Master's campaign, and the
things the graph already knows are named in it.

PASSAGE
{body}

THE THINGS IT NAMES, and the only names you may use:
{names}

What RELATIONSHIPS does the passage state between them? Only what it says or
directly implies -- not what is likely of people like these, and not anything
about a name that is not on the list.

USE ONLY THESE RELATIONSHIPS, AND ONLY BETWEEN THE TYPES SHOWN. The arrow is
`source -> target` and the direction matters.
{vocabulary}

Reply with JSON only:
{{"edges": [{{"source": "...", "rel_type": "...", "target": "..."}}]}}
Return an empty list rather than a doubtful edge."""


async def read_back(
    client: Any,
    *,
    body: str,
    names: tuple[str, ...],
    model: str,
    temperature: float = 0.0,
) -> tuple[tuple[dict, ...], str]:
    """What relationships a stored passage states between things already known.

    NOT `annotate`, AND THE DIFFERENCE MATTERS. That one is element-first: it
    asks a fresh generation to declare what it CONTAINS, and every name becomes
    a candidate to mint. Pointed at a section whose entities all already exist
    it did the only thing it could -- re-declared them as new elements, dropped
    five of six as kinds it may not mint, and proposed no relationships at all.
    Run over eight stored sections it found three edges, all in the one section
    that happened to be a fresh cluster.

    So this asks the narrower question the case actually poses: here is the
    prose, here are the names the scan already found in it, what holds between them.
    Nothing to mint, nothing to classify, one job.

    THE NAMES ARE GIVEN AND CLOSED. An edge naming something outside the list
    is about a thing this section does not discuss, and saying so up front is
    cheaper than dropping it afterwards.
    """
    # FEWER THAN TWO NAMES CANNOT RELATE TO ANYTHING, and the rule belongs
    # here rather than in whichever caller remembers it. A passage naming one
    # thing has no relationship to state, and paying a model to say so is
    # waste.
    if len(names) < 2 or not body.strip():
        return (), ""
    prompt = _READ_BACK.format(
        body=body,
        names="\n".join(f"  - {name}" for name in names),
        vocabulary=vocabulary_gloss(),
    )
    response = await client.chat.completions.create(
        model=model,
        messages=[{"role": "user", "content": prompt}],
        temperature=temperature,
        max_tokens=800,
    )
    data, error = _first_object(response.choices[0].message.content or "")
    if error:
        return (), error
    edges = [e for e in (data.get("edges") or ()) if isinstance(e, dict)]
    return tuple(edges), ""


async def annotate(
    client: Any,
    *,
    body: str,
    retrieval: Retrieval,
    depth: canon_context.Depth,
    model: str,
    #: What the material IS, so it cannot be listed among the things it
    #: contains. Optional because a caller that does not know it is no worse
    #: off than before this existed.
    subject: str = "",
    #: Its KIND, so the ontology can refuse an episode that may not sit in it.
    kind: str = "",
    temperature: float = 0.0,
    seed: int | None = None,
) -> tuple[tuple[dict, ...], tuple[dict, ...], dict, str]:
    """Ask the model what its own finished prose contains. `(elements, edges, dropped, error)`.

    THE SECOND CALL OF THE TWO-CALL VARIANT, and the reason it is worth a
    second call at all: declaring a manifest WHILE writing asks one response to
    invent and to classify at the same time, and measurement said it does both
    badly -- 37-51% of declared edges type-impossible even when shown the table
    that judges them, and an edge agreement of 0.18-0.35 between seeded runs
    against the extractor's 0.49.

    Annotation is a BOUNDED READING TASK over a fixed input, which is the kind
    of work this project already trusts a small model to do.

    THIS IS NOT THE EXTRACTOR. No layer passes, no consensus sampling, no
    `proposed` status -- and above all the text being read is the model's own,
    so a claim it makes here is the author restating an intent rather than a
    stranger inferring one.
    """
    shown = canon_context.apply(retrieval, depth)
    sources = canon_context.render(shown, max_edges=depth.max_edges)
    prompt = _ANNOTATE.format(
        body=body, vocabulary=vocabulary_gloss(), sources=sources,
        kinds=_KINDS_LINE, kind_gloss=ELEMENT_GLOSS,
    )
    response = await client.chat.completions.create(
        model=model,
        messages=[{"role": "user", "content": prompt}],
        temperature=temperature,
        max_tokens=1600,
        **({"seed": seed} if seed is not None else {}),
    )
    text = response.choices[0].message.content or ""
    data, error = parse_manifest(text)
    if error:
        return (), (), {}, error
    elements, edges, dropped = sift_manifest(data, subject, material_kind=kind)
    return elements, edges, dropped, ""


def parse_manifest(text: str) -> tuple[dict, str]:
    """A manifest-only response. Same tolerance and same strictness as `parse`."""
    cleaned = text.strip()
    if cleaned.startswith("```"):
        cleaned = cleaned.split("\n", 1)[-1]
        if cleaned.rstrip().endswith("```"):
            cleaned = cleaned.rstrip()[:-3]
    try:
        data = json.loads(cleaned)
    except json.JSONDecodeError as exc:
        return {}, f"annotation was not JSON: {exc}"
    if not isinstance(data, dict):
        return {}, "annotation was JSON but not an object"
    for name in ("elements", "edges"):
        if name not in data:
            return {}, f"annotation omitted {name!r}, so what it contains is undeclared"
    return data, ""


async def generate(
    client: Any,
    *,
    kind: str,
    subject: str,
    retrieval: Retrieval,
    depth: canon_context.Depth,
    model: str,
    temperature: float = 0.8,
    context: GenerationContext | None = None,
    cluster: bool = False,
    max_tokens: int = 1200,
    seed: int | None = None,
    previous: str = "",
    note: str = "",
) -> Generated:
    """Ask the model, then split what it says into sourced and invented.

    Temperature is higher than chat's 0.5 by default and that is deliberate:
    this is asked to invent, and the guard against invention leaking into canon
    is the required split, not a low temperature.
    """
    carried = context or GenerationContext()
    messages = build_messages(
        kind, subject, retrieval, depth, carried, cluster, previous, note
    )
    response = await client.chat.completions.create(
        model=model,
        messages=messages,
        temperature=temperature,
        max_tokens=max_tokens,
        # PASSED THROUGH so a caller measuring stability can actually pin the
        # draw. Without it, "temperature 0" alone still varies between calls,
        # and a stability figure taken that way is not comparable to one taken
        # with a seed -- which is exactly the comparison the cluster gate makes
        # against `extract.py`'s 0.49.
        **({"seed": seed} if seed is not None else {}),
    )
    text = response.choices[0].message.content or ""
    usage = Usage.from_response(response)
    cost = estimate(model, usage)
    data, error = parse(
        text, expect_context=not carried.empty, expect_cluster=cluster
    )
    elements, edges, manifest_dropped = (
        sift_manifest(data, subject, material_kind=kind) if cluster else ((), (), {})
    )

    shown = canon_context.apply(retrieval, depth)
    cites = canon_context.sources(shown)
    # Re-filed BEFORE the card is built, not only before it is written, so the
    # DM approves what is true rather than approving a green list and having it
    # quietly corrected underneath them. The same split runs again at the
    # persistence boundary, because this payload goes through a browser.
    book, yours = homebrew.split_by_origin(data.get("from_canon", ()) or (), cites)
    return Generated(
        kind=kind,
        subject=subject,
        title=str(data.get("title", "")),
        body=str(data.get("body", "")),
        from_canon=tuple(book),
        from_yours=tuple(yours),
        invented=tuple(data.get("invented", ()) or ()),
        from_context=tuple(data.get("from_context", ()) or ()),
        elements=elements,
        edges=edges,
        manifest_dropped=manifest_dropped,
        sources=tuple(cites),
        usage={"input": usage.input_tokens, "output": usage.output_tokens, "total": usage.total},
        cost=cost.as_dict(),
        retrieval={
            "path": retrieval.path,
            "anchors": [f"{a.surface} → {a.name}" for a in retrieval.anchors],
            "passages": len(shown.passages),
            "proposed_withheld": not depth.include_proposed,
            "miss_reason": retrieval.miss_reason,
            # Echoed back so the one thing that makes two identical requests
            # differ is visible in the answer that differed.
            "carried_entities": list(carried.entities),
            "carried_note": carried.note,
        },
        error=error,
        raw=text if error else "",
    )
