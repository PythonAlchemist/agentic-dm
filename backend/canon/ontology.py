"""What kinds of thing the canon graph holds, told to the model that queries it.

THE TOOLS WERE OFFERED WITHOUT A VOCABULARY. `graph_tools` gives the model
three named tools and about forty words each. Nothing told it that `SERVES` is
a relationship the graph records, or that `NPC` is a type it uses, so the only
ontology it ever saw was whatever instances happened to come back in a result:
`Strahd von Zarovich (LORE/MONSTER/NPC)` and one `-ALLIED_WITH->` arrow. It
learned the schema by example, from a sample it did not choose.

That is survivable while the tools are NAMED -- a model that cannot write a
query cannot name a label that does not exist -- but it costs two things.

**Absence stops meaning anything.** `expand` returning no `OWNS` edge for the
tavern could mean nobody owns it, or that the graph has no notion of ownership.
The model cannot tell, so it cannot say. This is the silent-zero failure this
project keeps finding, one level up: not an empty result read as "nothing
there", but an empty result that cannot be read at all.

**It is the precondition for generated Cypher.** A model composing a query must
know the label and relationship vocabulary or it will invent plausible ones --
`:Character`, `:LIVES_AT` -- and get an empty result rather than an error.

READ FROM THE GRAPH, NEVER WRITTEN DOWN HERE. A hardcoded list would be a
second claim about the corpus, free to disagree with the first the moment a
chapter is loaded, and telling a model that `GAVE_QUEST` exists when it does
not is worse than telling it nothing.

AND IT MUST AGREE WITH `EDGES`. `_RELATIONSHIPS` matches the same
`(:Entity {plane})-[r]->(:Entity {plane})` shape that `lookup.EDGES` does,
because this vocabulary is a promise about what `expand` can return. Matching
more loosely would advertise `REFERS_TO` and `IN_SECTION` -- the mention
plumbing, which is most of the graph's edges and which no tool surfaces.
"""

from __future__ import annotations

from dataclasses import dataclass

from backend.canon.lookup import CANON_PLANE, type_labels

#: Every type label in use, so the vocabulary is the same strings the tools
#: return. `type_labels` does the stripping, rather than a second rule here
#: that could disagree about whether the bare `:Entity` rung counts.
_LABELS = """
MATCH (n:Entity {plane:$plane}) UNWIND labels(n) AS label
RETURN DISTINCT label AS label
"""

#: Relationship types between two entities, and how many of each the book's own
#: structure derived. A type with no accepted edge at all is one the model may
#: never state as fact, and that is worth saying once here rather than hoping
#: it reads the status on every row.
_RELATIONSHIPS = """
MATCH (:Entity {plane:$plane})-[r]->(:Entity {plane:$plane})
RETURN type(r) AS rel,
       sum(CASE WHEN r.status = 'accepted' THEN 1 ELSE 0 END) AS accepted
"""


@dataclass(frozen=True)
class Ontology:
    """The vocabulary, split by how much of it can be trusted.

    `derived` and `guessed` are separated on the SAME line the rest of this
    codebase draws: a relationship type the book's structure produced is a
    fact, and one only an extractor ever produced is a lead. Measured on the
    Curse of Strahd corpus, exactly one type -- `CONTAINS` -- has any derived
    edges at all, and the other twenty-one are guesses end to end. A vocabulary
    that listed all twenty-two together would read as twenty-two kinds of
    knowledge, which would be the single most misleading thing this file could
    say.
    """

    entity_types: tuple[str, ...] = ()
    derived: tuple[str, ...] = ()
    guessed: tuple[str, ...] = ()

    def render(self) -> str:
        """The block the model reads. Empty string when the graph holds nothing.

        An empty graph renders NOTHING rather than an empty vocabulary: "the
        entity types are: " with a blank after it reads as a positive claim
        that there are none.
        """
        if not self.entity_types:
            return ""

        lines = [
            "THE CANON GRAPH's vocabulary. This is all of it -- a kind of thing "
            "not named here is not in the graph, so do not ask for one.",
            "",
            f"Entity types: {', '.join(self.entity_types)}",
        ]
        if self.derived:
            lines.append(
                "Relationships derived from the book's own structure, and "
                f"reliable: {', '.join(self.derived)}"
            )
        if self.guessed:
            lines.append(
                "Relationships an extractor guessed. About a third are wrong; "
                "offer one as a lead to check, never as fact: "
                f"{', '.join(self.guessed)}"
            )
        lines += [
            "",
            # The point of the whole block. Without it an empty result is
            # unreadable, and the model's only safe move is to say nothing.
            "A relationship type listed here that does not appear in an "
            "entity's results means the graph records none of that kind FOR "
            "THAT ENTITY -- which is a fact about the entity, not a gap in the "
            "graph. Every relationship returned also carries its own "
            "accepted/proposed status; trust that over this summary.",
        ]
        return "\n".join(lines)


def read(session, plane: str = CANON_PLANE) -> Ontology:
    """Ask the graph what it holds.

    NOT CACHED, deliberately. The two queries cost about 50ms against a
    multi-second model call, and a cache here would hold a vocabulary that had
    stopped being true -- silently listing what a reloaded corpus no longer
    contains, or omitting what it gained. Staleness is the expensive failure;
    50ms is not.
    """
    labels = [record["label"] for record in session.run(_LABELS, {"plane": plane})]
    rows = [dict(record) for record in session.run(_RELATIONSHIPS, {"plane": plane})]
    return Ontology(
        entity_types=tuple(type_labels(labels)),
        derived=tuple(sorted(r["rel"] for r in rows if r["accepted"])),
        guessed=tuple(sorted(r["rel"] for r in rows if not r["accepted"])),
    )
