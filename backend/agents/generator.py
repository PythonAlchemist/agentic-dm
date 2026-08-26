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
from backend.canon.retrieval import Retrieval
from backend.core.pricing import Usage, estimate

#: What can be generated. A closed set, checked before anything reaches a model:
#: an unknown kind would otherwise become an unconstrained prompt.
KINDS = ("quest", "npc", "monster", "scene")

#: What a CLUSTER may declare as a member. A separate closed set from `KINDS`,
#: because these are different questions: `KINDS` is what a DM may ask for on
#: its own, `ELEMENT_KINDS` is what a generation may say it contains. A
#: location, an item and a piece of lore are worth minting when a quest names
#: them and are not worth a generator of their own -- nobody asks the chat for
#: a bare LORE node.
ELEMENT_KINDS = ("npc", "monster", "location", "item", "lore")

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
    "scene": "an episode that happens at a point in the adventure: what "
             "occurs, where it interrupts the journey or the plan, who "
             "appears, how it can play out, and what it changes afterwards",
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
}

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
   `invented`. Do not pad `from_canon` to look better sourced.{context_rule}{cluster_rule}

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
4. The CONVERSATION block is a THIRD source and is neither of the first two.
   Anything you take from it goes in `from_context`. It is not the book, so it
   may not go in `from_canon`; it is not yours, so it may not go in `invented`."""

_CONTEXT_FIELD = """,
  "from_context": ["each detail taken from the conversation"]"""


def vocabulary_gloss() -> str:
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
    for name in homebrew_vocabulary():
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


def homebrew_vocabulary() -> tuple[str, ...]:
    """The relationship types a generation may declare between its elements.

    DERIVED FROM `LAYER_MAP`, exactly as `extract.layer_vocabulary` derives the
    extractor's, so one table feeds both pipelines and adding a type cannot
    leave either silently unaware of it. The types mapped to NO layer are the
    ones excluded, and they are excluded correctly without a hand-written
    denylist: `ATTENDED`, `PLAYS_AS`, `HAS_CLASS` and their kind are session
    bookkeeping and runtime state, not the authored world a DM invents.
    """
    from backend.graph.schema import LAYER_MAP

    return tuple(sorted(r.value for r, layer in LAYER_MAP.items() if layer is not None))


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
   lore -- goes in `elements`, each with its OWN three provenance lists, split
   by the same rule as above. Relationships between them go in `edges`.
   Name an element by its `name`; name something from the CANON passages by
   the id shown beside it, and never by an id you were not shown.
   An element you would only mention in passing is scenery -- leave it out.

   USE ONLY THESE RELATIONSHIPS, AND ONLY BETWEEN THE TYPES SHOWN. The arrow
   is `source -> target` and the direction matters: an edge whose endpoints
   are the wrong types is DISCARDED, so check the line before you write one.
{vocabulary}"""

_CLUSTER_FIELD = """,
  "elements": [{{"kind": "npc|monster|location|item|lore", "name": "...",
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


def build_messages(
    kind: str,
    subject: str,
    retrieval: Retrieval,
    depth: canon_context.Depth,
    context: GenerationContext | None = None,
    cluster: bool = False,
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
    system = canon_context.render(shown, max_edges=depth.max_edges)
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
                context_rule=_CONTEXT_RULE if not carried.empty else "",
                context_field=_CONTEXT_FIELD if not carried.empty else "",
                # Numbered after whatever came before it, so the rules read as
                # a list rather than jumping from 3 to 4 with a gap where the
                # context rule would have been.
                cluster_rule=(
                    _CLUSTER_RULE.format(
                        n=5 if not carried.empty else 4,
                        vocabulary=vocabulary_gloss(),
                    )
                    if cluster
                    else ""
                ),
                cluster_field=_CLUSTER_FIELD if cluster else "",
            ),
        },
    ]


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
    cleaned = text.strip()
    if cleaned.startswith("```"):
        cleaned = cleaned.split("\n", 1)[-1]
        if cleaned.rstrip().endswith("```"):
            cleaned = cleaned.rstrip()[: -3]
    try:
        data = json.loads(cleaned)
    except json.JSONDecodeError as exc:
        return {}, f"response was not JSON: {exc}"
    if not isinstance(data, dict):
        return {}, "response was JSON but not an object"
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


def sift_manifest(data: dict) -> tuple[tuple[dict, ...], tuple[dict, ...], dict]:
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

{{"elements": [{{"kind": "npc|monster|location|item|lore", "name": "...",
                "role": "what it is here, in one line",
                "from_canon": [{{"claim": "...", "cite": "[1]"}}],
                "invented": ["..."]}}],
  "edges": [{{"source": "...", "target": "...", "rel_type": "LOCATED_IN",
             "provenance": "canon|invented", "cite": "[1]"}}]}}"""


async def annotate(
    client: Any,
    *,
    body: str,
    retrieval: Retrieval,
    depth: canon_context.Depth,
    model: str,
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
        body=body, vocabulary=vocabulary_gloss(), sources=sources
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
    elements, edges, dropped = sift_manifest(data)
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
) -> Generated:
    """Ask the model, then split what it says into sourced and invented.

    Temperature is higher than chat's 0.5 by default and that is deliberate:
    this is asked to invent, and the guard against invention leaking into canon
    is the required split, not a low temperature.
    """
    carried = context or GenerationContext()
    messages = build_messages(kind, subject, retrieval, depth, carried, cluster)
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
    elements, edges, manifest_dropped = sift_manifest(data) if cluster else ((), (), {})

    shown = canon_context.apply(retrieval, depth)
    return Generated(
        kind=kind,
        subject=subject,
        title=str(data.get("title", "")),
        body=str(data.get("body", "")),
        from_canon=tuple(data.get("from_canon", ()) or ()),
        invented=tuple(data.get("invented", ()) or ()),
        from_context=tuple(data.get("from_context", ()) or ()),
        elements=elements,
        edges=edges,
        manifest_dropped=manifest_dropped,
        sources=tuple(canon_context.sources(shown)),
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
