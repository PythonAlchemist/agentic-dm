"""The seam between the chat agent and the generator sub-agent.

TWO AGENTS, ONE GENERATOR. The Generate tab calls the generator directly with a
subject a person typed; chat calls the SAME generator as a tool with context
attached. One implementation, two callers -- so an improvement to generation
reaches both, and neither can drift into being the good one.

WHAT THE MODEL MAY SAY, AND WHAT IT MAY NOT. The tool takes a request and
returns an acknowledgement. It does NOT return prose for the model to weave
into its answer, and that is the whole point: a model that could emit invented
NPCs inline would be producing invention in an answer's clothes, with no
`from_canon`/`invented` envelope around it. The envelope is enforced at the
schema level precisely because it must be a contract. So generation happens
after the tool loop, the result becomes a CARD, and a person approves it.

EVERY ARGUMENT IS CHECKED AGAINST WHAT THE CONVERSATION ACTUALLY HOLDS.
`context_entity_ids` must name entities in the subgraph and `insert_after` must
name a section the session has seen -- a constrained menu, not free text. A
model inventing an id would otherwise put a stranger's name into a generation,
or anchor a scene into a chapter nobody has opened.
"""

from __future__ import annotations

from dataclasses import dataclass

from backend.agents.generator import KINDS

#: The most entities a single generation may carry from the conversation. The
#: subgraph is cumulative across a whole session and has held ~50 edges on one
#: turn; handing all of it over would bury the subject in everything else the
#: table has discussed. Six is enough to name a scene's cast.
MAX_CONTEXT = 6

SCHEMA = {
    "type": "function",
    "function": {
        "name": "generate_homebrew",
        "description": (
            "Draft new material for the DM to review -- a quest, NPC, monster, "
            "or a scene inserted into the adventure's running order. Use when "
            "the DM asks you to make something up, not to answer questions "
            "about the book. Returns nothing you can quote: the draft goes to "
            "the DM as a card they approve or discard, so do not write the "
            "content yourself, and tell them a draft is ready for review."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "kind": {
                    "type": "string",
                    "enum": list(KINDS),
                    "description": (
                        "`scene` for an episode inserted at a point in the "
                        "adventure, such as an encounter during a journey."
                    ),
                },
                "subject": {
                    "type": "string",
                    "description": "What to make, in the DM's own terms.",
                },
                "context_entity_ids": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": (
                        f"At most {MAX_CONTEXT} ids from IN THIS CONVERSATION "
                        "that this material should involve. Ids only, exactly "
                        "as listed there."
                    ),
                },
                "insert_after_section_id": {
                    "type": "string",
                    "description": (
                        "For a `scene`: the id of the cited section it happens "
                        "during or after, from the passages above. Omit if the "
                        "DM has not said where it goes."
                    ),
                },
                "note": {
                    "type": "string",
                    "description": (
                        "Anything the DM has established at the table that is "
                        "not in the book and this should respect."
                    ),
                },
            },
            "required": ["kind", "subject"],
        },
    },
}


@dataclass(frozen=True)
class Request:
    """One validated ask. Everything in it has been checked to exist."""

    kind: str
    subject: str
    context_entity_ids: tuple[str, ...] = ()
    insert_after: str = ""
    note: str = ""
    #: Ids the model named that the conversation does not hold, and section ids
    #: it never saw. Reported back to it rather than silently dropped: a model
    #: that cannot see its mistake makes it again next round.
    rejected: tuple[str, ...] = ()

    @property
    def acknowledgement(self) -> dict:
        """What the MODEL gets back. Deliberately not the material."""
        message = (
            f"A {self.kind} draft has been prepared for the DM to review as a "
            "card. Do not write it out yourself -- tell them it is ready and "
            "ask if they want anything changed."
        )
        payload = {"queued": True, "kind": self.kind, "subject": self.subject}
        if self.insert_after:
            payload["insert_after"] = self.insert_after
        if self.rejected:
            payload["ignored"] = list(self.rejected)
            message += (
                f" Note: {len(self.rejected)} id(s) you gave are not in this "
                "conversation and were ignored."
            )
        payload["instruction"] = message
        return payload


def validate(
    arguments: dict, *, held_ids: frozenset[str], seen_sections: frozenset[str]
) -> tuple[Request | None, str]:
    """Check an ask against what this conversation holds. `(request, error)`.

    Pure over the two id sets, so the contract can be tested without a graph,
    a model, or a session.
    """
    kind = str(arguments.get("kind", "")).strip()
    if kind not in KINDS:
        return None, f"unknown kind {kind!r}; expected one of {sorted(KINDS)}"

    subject = str(arguments.get("subject", "")).strip()
    if not subject:
        return None, "a generation needs a subject saying what to make"

    raw_ids = arguments.get("context_entity_ids") or []
    if not isinstance(raw_ids, list):
        return None, "context_entity_ids must be a list of ids"

    kept, rejected = [], []
    for entity_id in raw_ids:
        target = kept if str(entity_id) in held_ids else rejected
        target.append(str(entity_id))
    if len(kept) > MAX_CONTEXT:
        # Truncated rather than refused, and the cut is reported: a model that
        # over-supplies context has still asked for something reasonable.
        rejected.extend(kept[MAX_CONTEXT:])
        kept = kept[:MAX_CONTEXT]

    anchor = str(arguments.get("insert_after_section_id") or "").strip()
    if anchor and anchor not in seen_sections:
        rejected.append(anchor)
        anchor = ""

    return (
        Request(
            kind=kind,
            subject=subject,
            context_entity_ids=tuple(kept),
            insert_after=anchor,
            note=str(arguments.get("note") or "").strip(),
            rejected=tuple(rejected),
        ),
        "",
    )
