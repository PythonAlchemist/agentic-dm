"""Generate a quest, an NPC or a monster, with canon and invention kept apart.

THE SPLIT IS THE PRODUCT. Anything a model writes about Barovia will read like
the book -- that is what it is good at -- and a DM who cannot tell which half
came from the adventure will eventually contradict the adventure at the table,
or worse, treat an invented detail as a fact the players have already been told.
So the model is required to return two lists: what it took from the supplied
passages, each citing one, and what it made up.

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
KINDS = ("quest", "npc", "monster")

_SHAPES = {
    "quest": "a quest hook: who gives it, what it asks, what stands in the way, "
             "and what completing it changes",
    "npc": "a non-player character: name, what they do, how they behave, what "
           "they want, and one thing they are hiding",
    "monster": "a creature encounter: what it is, where it is met, how it "
               "fights, and what a party can learn from it",
}

_INSTRUCTIONS = """You generate material for a Dungeon Master running Curse of Strahd.

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

Return ONLY JSON, of this shape:

{{"title": "...",
  "body": "the generated material, written for a DM to read aloud or run from",
  "from_canon": [{{"claim": "what the book establishes", "cite": "[1]"}}],
  "invented": ["each detail you supplied"]}}"""


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
            "sources": list(self.sources),
            "usage": self.usage,
            "cost": self.cost,
            "retrieval": self.retrieval,
            "error": self.error,
            "raw": self.raw,
        }


def build_messages(
    kind: str, subject: str, retrieval: Retrieval, depth: canon_context.Depth
) -> list[dict]:
    """The exact messages the model will see. Pure, so a test can read them."""
    if kind not in KINDS:
        raise ValueError(f"unknown kind {kind!r}; expected one of {KINDS}")
    shown = canon_context.apply(retrieval, depth)
    return [
        {"role": "system", "content": canon_context.render(shown, max_edges=depth.max_edges)},
        {
            "role": "user",
            "content": _INSTRUCTIONS.format(shape=_SHAPES[kind], subject=subject),
        },
    ]


def parse(text: str) -> tuple[dict, str]:
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
    for required in ("from_canon", "invented"):
        if required not in data:
            return {}, f"response omitted {required!r}, so canon and invention are not separated"
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
) -> Generated:
    """Ask the model, then split what it says into sourced and invented.

    Temperature is higher than chat's 0.5 by default and that is deliberate:
    this is asked to invent, and the guard against invention leaking into canon
    is the required split, not a low temperature.
    """
    messages = build_messages(kind, subject, retrieval, depth)
    response = await client.chat.completions.create(
        model=model, messages=messages, temperature=temperature, max_tokens=1200
    )
    text = response.choices[0].message.content or ""
    usage = Usage.from_response(response)
    cost = estimate(model, usage)
    data, error = parse(text)

    shown = canon_context.apply(retrieval, depth)
    return Generated(
        kind=kind,
        subject=subject,
        title=str(data.get("title", "")),
        body=str(data.get("body", "")),
        from_canon=tuple(data.get("from_canon", ()) or ()),
        invented=tuple(data.get("invented", ()) or ()),
        sources=tuple(canon_context.sources(shown)),
        usage={"input": usage.input_tokens, "output": usage.output_tokens, "total": usage.total},
        cost=cost.as_dict(),
        retrieval={
            "path": retrieval.path,
            "anchors": [f"{a.surface} → {a.name}" for a in retrieval.anchors],
            "passages": len(shown.passages),
            "proposed_withheld": not depth.include_proposed,
            "miss_reason": retrieval.miss_reason,
        },
        error=error,
        raw=text if error else "",
    )
