"""What a model may ask the graph for. Named tools, not free Cypher.

Increment 3 of the conversational-subgraph design. The DM agent decides what it
needs and calls one of these; each is a deterministic function over a session
that cannot write. A model choosing WHICH tool to call is a guess about where
to look, the same class of decision as Lucene's score choosing which sections
to read -- and, like that one, it is a guess over facts that stay checkable.

NAMED RATHER THAN GENERATED, DELIBERATELY, AND FIRST. Generated Cypher is the
next increment and needs a harness that can catch it being wrong; a fixed set
of tools cannot emit a bad query at all. Everything here runs a query this
repository wrote, so the four invariants the design rests on hold by
construction rather than by wrapping something a model composed:

  read-only   every call goes through `read_only_session`, which exposes `run`
              and nothing else. See there for why a configured session is not
              enough on its own.
  status      every edge carries `accepted` or `proposed`. A third of proposed
              edges are false, and one that arrived without its status would be
              a guess wearing a fact's clothes.
  plane       every query filters `plane`, so canon and campaign never blur.
  bounded     every tool takes a limit and reports what it cut, because a
              silent truncation reads as "that is all there is".

THE QUERIES ARE THE LOOKUP'S QUERIES. `EDGES` and `MENTIONS` are imported
rather than rewritten: a second definition of "the relationships of an entity"
would be free to disagree with the first about direction or about status, and
direction reversal is one of the extractor's measured failure modes.
"""

from __future__ import annotations

from dataclasses import dataclass

from backend.canon.aliases import normalize
from backend.canon.lookup import CANON_PLANE, EDGES, MENTIONS, type_labels
from backend.canon.retrieval import BY_ALIAS
from backend.core.database import read_only_session

#: What one call may return. A model asked to read two hundred rows will read
#: the first few and answer as though it had read them all.
DEFAULT_LIMIT = 12


@dataclass(frozen=True)
class Result:
    """What a tool found, and what it did not return.

    `cut` is separate from `rows` and never folded into it. A tool that
    returned twelve of ninety edges and said only "twelve" would let a model
    conclude an entity has twelve relationships.
    """

    rows: tuple[dict, ...]
    cut: int = 0

    @property
    def as_dict(self) -> dict:
        return {"rows": list(self.rows), "cut": self.cut}


def _bounded(rows: list[dict], limit: int) -> Result:
    return Result(tuple(rows[:limit]), max(0, len(rows) - limit))


def resolve(name: str, plane: str = CANON_PLANE) -> Result:
    """Which entities answer to a name. Several is a legitimate answer.

    THE ALIAS PATH, and the only one. `Barovia` names a region and a village;
    `Tatyana` is an NPC and a piece of lore. Collapsing those to one would be
    the graph choosing on a reader's behalf between things the book genuinely
    distinguishes -- so the ambiguity travels, and a model that gets two rows
    has been told there are two.

    Never a fuzzy match. A caller wanting `Strahd` to reach `Strahd von
    Zarovich` needs `Strahd` recorded as an alias, which is the whole mechanism
    and is the mechanism precisely because the alternatives have twice put
    wrong answers in this graph.
    """
    with read_only_session() as session:
        found = [
            dict(record)
            for record in session.run(
                BY_ALIAS,
                # `campaign_prefix: None` DELIBERATELY, not by omission: these
                # tools read canon and only canon, so a campaign's own names
                # must not resolve through them. The parameter is required by
                # the query rather than defaulted inside it, which is why this
                # says so out loud instead of leaving it out.
                {
                    "normalized": normalize(name),
                    "plane": plane,
                    "book": None,
                    "campaign_prefix": None,
                },
            )
        ]
    # `BY_ALIAS` rather than `aliases.RESOLVE_BY_NAME`: that one returns ids
    # alone, and a caller holding an id with no name cannot put the entity into
    # the subgraph or say it back to a reader. Labels go through `type_labels`
    # so what comes out is NPC or LOCATION rather than the raw label set with
    # `Entity` and the hierarchy rung mixed in.
    rows = [
        {
            "entity_id": row["id"],
            "name": row["name"],
            "labels": type_labels(row["labels"]),
            "status": row["node_status"],
        }
        for row in found
    ]
    return Result(tuple(rows))


def expand(entity_id: str, limit: int = DEFAULT_LIMIT, plane: str = CANON_PLANE) -> Result:
    """The relationships of one entity, in the direction the graph stores them.

    BOTH DIRECTIONS, because half of what a DM wants about an NPC is written
    with the NPC as the target -- who serves Strahd is an inbound edge from
    Strahd's side. `direction` says which, so a caller can write the arrow the
    right way round rather than guessing from the phrasing.

    Accepted first, then proposed, then by name. A model reading a truncated
    list should meet the derived facts before the guesses rather than whichever
    the driver returned first.
    """
    with read_only_session() as session:
        rows = [
            dict(record)
            for record in session.run(EDGES, {"ids": [entity_id], "plane": plane})
        ]
    rows.sort(key=lambda r: (r.get("status") != "accepted", str(r.get("other"))))
    return _bounded(rows, limit)


def passages(entity_id: str, limit: int = DEFAULT_LIMIT, plane: str = CANON_PLANE) -> Result:
    """Where in the book an entity is named, loudest section first.

    The TEXT is not returned. A section's prose is 82% of a turn's input and the
    retrieval path already sends it; a tool that returned it again would double
    the largest thing in the context to tell a model something it can already
    read. What comes back is where to look -- chapter, heading, section id and
    how loudly that section names the entity.
    """
    with read_only_session() as session:
        found = [
            dict(record)
            for record in session.run(
                MENTIONS, {"ids": [entity_id], "plane": plane, "book_slug": None}
            )
        ]
    rows = [
        {
            "section_id": f"cos:{row['chapter']}#{row['section_index']}",
            "chapter": row["chapter"],
            "section": row["section"],
            "occurrences": row["occurrences"],
            "aliases": row["aliases"],
        }
        for row in found
    ]
    rows.sort(key=lambda r: (-(r["occurrences"] or 0), r["section_id"]))
    return _bounded(rows, limit)


#: What the model is offered, in the shape the OpenAI tool API wants.
#:
#: Descriptions are written for the CALLER rather than for a reader of this
#: file: they say when to reach for a tool, because a model choosing badly
#: between three tools is the failure mode this increment can actually have.
SCHEMA = [
    {
        "type": "function",
        "function": {
            "name": "resolve",
            "description": (
                "Find the canon entities a name refers to. Use when the "
                "conversation mentions something by name that is not already "
                "listed under IN THIS CONVERSATION. May return several "
                "entities for one name; that ambiguity is real."
            ),
            "parameters": {
                "type": "object",
                "properties": {"name": {"type": "string"}},
                "required": ["name"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "expand",
            "description": (
                "List an entity's relationships. Use for questions about who "
                "serves, owns, opposes or is related to whom. Edges marked "
                "proposed are extractor guesses and about a third are wrong."
            ),
            "parameters": {
                "type": "object",
                "properties": {"entity_id": {"type": "string"}},
                "required": ["entity_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "passages",
            "description": (
                "List where in the book an entity is named, loudest first. Use "
                "to find which section to read; it returns locations, not text."
            ),
            "parameters": {
                "type": "object",
                "properties": {"entity_id": {"type": "string"}},
                "required": ["entity_id"],
            },
        },
    },
]

TOOLS = {"resolve": resolve, "expand": expand, "passages": passages}


def call(name: str, arguments: dict) -> Result:
    """Run one tool by name. An unknown name is an error, never a no-op.

    A model naming a tool that does not exist has misunderstood what it was
    offered, and returning an empty result would let it conclude the graph
    holds nothing -- which is the silent-zero failure this project keeps
    finding and removing.
    """
    tool = TOOLS.get(name)
    if tool is None:
        raise KeyError(f"no such tool {name!r}; offered: {sorted(TOOLS)}")
    return tool(**arguments)
