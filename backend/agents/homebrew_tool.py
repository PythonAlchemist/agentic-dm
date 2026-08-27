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
            "Draft NEW material for the DM to review -- a quest, NPC, monster, "
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
                        "WHAT IT IS DECIDES WHETHER THE DM GETS A CAST OR A "
                        "PARAGRAPH. `scene` and `quest` CONTAIN things: every "
                        "person, place and object they name is pulled out "
                        "afterwards and stored as its own entry the DM can "
                        "review one by one. `npc` and `monster` ARE one thing "
                        "and produce a single write-up.\n"
                        "So: `scene` for an episode at a point in the "
                        "adventure — an encounter during a journey, an ambush, "
                        "a confrontation — and for ANY request naming several "
                        "things at once: a cast, a crew, a group of enemies, "
                        "'a table of', 'who is aboard'. `encounter` when what "
                        "they want is a FIGHT they can run — enemies with "
                        "counts, tactics and terrain — rather than a narrative "
                        "beat. `quest` for a job "
                        "somebody is given. `npc` or `monster` only when the "
                        "DM wants exactly one creature or person described."
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
    #: The section this REPLACES rather than sits beside. Set when the DM asked
    #: to change something that already exists, which is a different act from
    #: making a new thing and has to reach the card as one -- otherwise
    #: "build out the sea battle" mints a second sea battle beside the first.
    revises: str = ""
    #: The entity this gives its FIRST prose to. A stub has a name and a role
    #: and nothing else; "flesh this out" about one is a write, not a rewrite.
    expands: str = ""
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


#: The other half of the seam: not "make something", but "show me what I made".
#:
#: THE CHAT HAD NO WAY TO READ THE CAMPAIGN. Its only actionable tool was
#: `generate_homebrew`, described as "use when the DM asks you to make
#: something up" -- so "lets revisit the homebrew content about the sea battle"
#: had exactly one place to go, and it went there and drafted a new scene. The
#: roster in the context block fixes knowing WHAT exists; this fixes reading it.
#:
#: NAMED, NOT ID'D. A DM says "the sea battle", not `hb:p13-home:the-sea-battle`,
#: and the roster the model was shown lists names. Resolution is the campaign's
#: own aliases, case-folded, for the reason retrieval folds them: these are a
#: few dozen names the person asking wrote themselves.
READ_SCHEMA = {
    "type": "function",
    "function": {
        "name": "read_my_material",
        "description": (
            "Read what this table has already made -- the DM's own scenes, "
            "NPCs, quests and places, not the published book. Use whenever "
            "they ask about something listed under EVERYTHING THIS TABLE HAS "
            "MADE and its words are not already in the passages above. Use it "
            "BEFORE offering to write anything: they usually mean the thing "
            "they already have."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "name": {
                    "type": "string",
                    "description": (
                        "The name as it appears in that list. Omit to get "
                        "everything this table has made."
                    ),
                }
            },
            "required": [],
        },
    },
}


#: The third verb. `generate_homebrew` makes something new and
#: `read_my_material` shows what exists; neither could CHANGE it, so a DM
#: looking at their own one-sentence scene and asking to build it out got a
#: second scene beside the first.
#:
#: IT IS NOT `expand`. That turns a stub with no prose into prose. This rewrites
#: prose that is already there, keeping what nobody objected to -- the same
#: revision path the card offers, reached by asking instead of by typing in a
#: box.
REVISE_SCHEMA = {
    "type": "function",
    "function": {
        "name": "revise_my_material",
        "description": (
            "Write or rewrite something the DM already has. If it has prose, "
            "this keeps what they did not ask you to change; if it is only a "
            "name and a role, this gives it its first write-up. Use when they "
            "say flesh this out, build this out, add to it, "
            "make it longer, change X about it, or otherwise talk about "
            "altering a thing that exists -- especially the one named at the "
            "top of the context as what they are reading. Do NOT use "
            "generate_homebrew for that: it would make a second copy beside "
            "the first. Returns nothing you can quote; the rewrite goes to the "
            "DM as a card they approve."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "name": {
                    "type": "string",
                    "description": (
                        "PASS THE NAME THE DM TYPED, and nothing else. If "
                        "they wrote a name — 'flesh out A Bent Turnkey' — pass "
                        "exactly that. If they pointed instead of naming — "
                        "'this', 'it', 'him', 'her', 'this character', 'this "
                        "scene' — omit this field entirely and the thing they "
                        "are reading is used. Never supply a name they did not "
                        "write: choosing one from the list is how a request to "
                        "flesh out the character on screen became a draft of a "
                        "different one."
                    ),
                },
                "note": {
                    "type": "string",
                    "description": (
                        "The change they asked for, in their own words: "
                        "'build out the enemies', 'make her older', 'cut the "
                        "storm'."
                    ),
                },
            },
            "required": ["note"],
        },
    },
}


READ = """
MATCH (e:Entity {plane:'campaign', campaign:$campaign})
WHERE $name IS NULL OR toLower(e.name) = toLower($name)
OPTIONAL MATCH (s:Section {expands:e.id})
RETURN e.name AS name, e.kind AS kind, e.role AS role, s.text AS text,
       s.id AS section_id
ORDER BY e.kind, e.name
"""


def read(session, campaign: str, name: str = "") -> dict:
    """What the campaign holds under this name, or all of it.

    RETURNS THE PROSE, unlike `generate_homebrew`, and that asymmetry is the
    point: this is the DM's own material being read back to them, not invention
    arriving without an envelope around it. There is nothing to keep apart --
    every word of it is theirs.

    A NAME THAT MATCHES NOTHING SAYS SO, and says what there is. A tool that
    returned an empty result would read as "you have made nothing", which is
    the failure this whole change exists to stop.
    """
    rows = [dict(r) for r in session.run(READ, {"campaign": campaign, "name": name or None})]
    if not rows and name:
        available = [
            dict(r)["name"]
            for r in session.run(READ, {"campaign": campaign, "name": None})
        ]
        return {
            "found": None,
            "asked_for": name,
            "note": f"nothing here is called {name!r}",
            "this_table_has": available,
        }
    return {
        "found": [
            {
                "name": r["name"],
                "kind": r["kind"],
                "role": r["role"],
                "text": r["text"],
                "written": bool(r["text"]),
            }
            for r in rows
        ]
    }


RESOLVE_REVISION = """
MATCH (e:Entity {plane:'campaign', campaign:$campaign})
WHERE ($name <> '' AND toLower(e.name) = toLower($name))
   OR ($name = '' AND ($focus = e.id OR $focus STARTS WITH e.id + '#'))
OPTIONAL MATCH (s:Section {expands: e.id})
RETURN e.id AS entity_id, e.name AS name, e.kind AS kind, e.role AS role,
       s.id AS section_id, s.text AS text
LIMIT 1
"""


def resolve_revision(session, *, campaign: str, name: str, focus: str) -> dict | None:
    """Which stored thing "flesh this out" is about, and whether it has prose.

    A STUB RESOLVES TOO, and `section_id` comes back empty for it. It used to
    resolve to nothing on the reasoning that a rewrite needs something to
    rewrite -- true of the machinery and false of the DM, who says "flesh out
    this character" without checking first whether they ever wrote a paragraph
    about them. Asked that of Captain Saltmarrow, the model had no verb for it,
    reached for `generate_homebrew`, and drafted a different NPC entirely.

    So the caller decides: prose means rewrite it, no prose means write the
    first one. One act to a person, two writes underneath.

    The focus may be an entity id or the id of its section; both mean the same
    thing to a person, so both are accepted.
    """
    row = session.run(
        RESOLVE_REVISION, {"campaign": campaign, "name": name, "focus": focus}
    ).single()
    return dict(row) if row else None


#: The fourth verb. `generate` makes, `read` shows, `revise` rewrites -- and
#: none of them could MOVE anything, so a DM who could see their encounter
#: sitting in the wrong place had to reach for a mouse to say so.
#:
#: ONE TOOL FOR BOTH AXES, because a person says "put the encounter inside the
#: sea battle" and "put it after the ambush" in the same breath and does not
#: think of them as different operations. The graph keeps them apart --
#: `PART_OF` is containment and the chain is sequence -- and this is the seam
#: where one sentence becomes whichever of them was meant.
ARRANGE_SCHEMA = {
    "type": "function",
    "function": {
        "name": "arrange_running_order",
        "description": (
            "Move something in the running order: put it inside another thing, "
            "or after another thing, or both. Use when the DM says a scene is "
            "in the wrong place, belongs inside something, should come before "
            "or after something, or should be pulled out to the top level. "
            "Only their own material can be moved; the book's own sections "
            "stay where the book put them."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "what": {
                    "type": "string",
                    "description": (
                        "The thing to move, by name. Omit to move what they "
                        "are reading."
                    ),
                },
                "inside": {
                    "type": "string",
                    "description": (
                        "What it should sit INSIDE, by name. Pass an empty "
                        "string to pull it out to the top level. Omit to leave "
                        "its parent alone."
                    ),
                },
                "after": {
                    "type": "string",
                    "description": (
                        "What it should come immediately AFTER, by name. Omit "
                        "to leave its position alone."
                    ),
                },
            },
            "required": [],
        },
    },
}


BY_HEADING = """
MATCH (s:Section)
WHERE (s.plane = 'canon' OR s.campaign = $campaign)
  AND toLower(s.heading) = toLower($heading)
RETURN s.id AS id, s.heading AS heading, s.plane AS plane, s.kind AS kind,
       s.depth AS depth
ORDER BY s.plane DESC
LIMIT 1
"""


def section_by_name(session, campaign: str, heading: str) -> dict | None:
    """One section by what it is CALLED, across both planes.

    A DM says "the sea battle", not `hb:p13-home:the-sea-battle#0`, and every
    list they have been shown is a list of headings.

    THEIR OWN WINS A TIE. `ORDER BY s.plane DESC` puts `campaign` above
    `canon`, so a scene they wrote and named after a section of the book
    resolves to theirs -- which is the one they can actually move, and the one
    they meant.
    """
    row = session.run(
        BY_HEADING, {"campaign": campaign, "heading": heading}
    ).single()
    return dict(row) if row else None


def named_by_the_dm(name: str, message: str) -> bool:
    """Did the DM actually say this name, or did the model choose it?

    A NAME NOBODY TYPED IS A NAME THE MODEL PICKED. Asked to "flesh out this
    character" with Captain Saltmarrow on screen, it kept answering with `name:
    "A Bent Turnkey"` -- a different NPC, taken from the roster because that
    one is marked as having no prose yet and "flesh out" sounds like it. The
    instruction not to do that is in the context twice and it still happened in
    two runs out of three.

    So it is checked rather than asked for. The DM's own words are the
    evidence: if the name is not in what they typed, they were pointing at
    something, and what they were pointing at is the focus.

    Loose on purpose -- "saltmarrow" should match "Captain Saltmarrow", and a
    DM writes the short form far more often than the full one. The cost of a
    false match is using a name they did say; the cost of a false miss is using
    the thing in front of them. Neither is bad, which is why the loose test is
    the right one.
    """
    words = [w for w in name.casefold().replace("'", "").split() if len(w) > 3]
    said = message.casefold().replace("'", "")
    return any(word in said for word in words) if words else name.casefold() in said
