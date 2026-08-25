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
from dataclasses import dataclass
from typing import Any

from backend.agents import canon_context
from backend.canon.retrieval import Retrieval
from backend.core.pricing import Usage, estimate

#: What can be generated. A closed set, checked before anything reaches a model:
#: an unknown kind would otherwise become an unconstrained prompt.
KINDS = ("quest", "npc", "monster", "scene")

_SHAPES = {
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
   `invented`. Do not pad `from_canon` to look better sourced.{context_rule}

Return ONLY JSON, of this shape:

{{"title": "...",
  "body": "the generated material, written for a DM to read aloud or run from",
  "from_canon": [{{"claim": "what the book establishes", "cite": "[1]"}}],
  "invented": ["each detail you supplied"]{context_field}}}"""

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
) -> list[dict]:
    """The exact messages the model will see. Pure, so a test can read them.

    `context` is what a CONVERSATION handed over, rendered as its OWN block
    under its own heading and never merged into the canon block. A DM's remark
    and the book's sentence must not reach the model looking alike -- that is
    the same rule the accepted/proposed headings follow, applied to a source
    the generator did not have until chat could call it.
    """
    if kind not in KINDS:
        raise ValueError(f"unknown kind {kind!r}; expected one of {KINDS}")
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
                shape=_SHAPES[kind],
                subject=subject,
                # The retrieval knows which book it read; this used to name one.
                book=retrieval.book_title or "this adventure",
                # Asked for only when there is a third source to ask about: a
                # required list that is always empty teaches the model to ignore
                # it, and this one has to mean something the day it is used.
                context_rule=_CONTEXT_RULE if not carried.empty else "",
                context_field=_CONTEXT_FIELD if not carried.empty else "",
            ),
        },
    ]


def parse(text: str, *, expect_context: bool = False) -> tuple[dict, str]:
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
    for field_name in required:
        if field_name not in data:
            return {}, (
                f"response omitted {field_name!r}, so its sources are not separated"
            )
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
) -> Generated:
    """Ask the model, then split what it says into sourced and invented.

    Temperature is higher than chat's 0.5 by default and that is deliberate:
    this is asked to invent, and the guard against invention leaking into canon
    is the required split, not a low temperature.
    """
    carried = context or GenerationContext()
    messages = build_messages(kind, subject, retrieval, depth, carried)
    response = await client.chat.completions.create(
        model=model, messages=messages, temperature=temperature, max_tokens=1200
    )
    text = response.choices[0].message.content or ""
    usage = Usage.from_response(response)
    cost = estimate(model, usage)
    data, error = parse(text, expect_context=not carried.empty)

    shown = canon_context.apply(retrieval, depth)
    return Generated(
        kind=kind,
        subject=subject,
        title=str(data.get("title", "")),
        body=str(data.get("body", "")),
        from_canon=tuple(data.get("from_canon", ()) or ()),
        invented=tuple(data.get("invented", ()) or ()),
        from_context=tuple(data.get("from_context", ()) or ()),
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
