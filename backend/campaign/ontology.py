"""What kinds of thing a story is made of, and which of them can hold others.

THE RUNNING ORDER WAS A FLAT LIST AND A STORY IS NOT ONE. Every insertion went
BETWEEN two things at one level, so "The Sea Battle Encounter" -- a fight that
happens during The Sea Battle -- could only be placed as its sibling, sitting
before the scene it occurs inside. The chain models SEQUENCE and a story also
has CONTAINMENT, and conflating the two is what made a correct placement
impossible to express.

THE BOOK ALREADY KNEW. Every canon section carries `depth` and `parent_index`
from the harvest: `Prisoner 13` at depth 1 holds `Varrin's Proposition` at
depth 2, which holds `The Breaker's Map` at depth 3. The hierarchy has been in
the graph since the beginning and the running order discarded it.

TWO AXES, KEPT APART.

    containment   what a thing is INSIDE      (parent)
    sequence      what comes before it        (the chain, among siblings)

A thing has both. Reordering siblings must not change what they are inside, and
moving something into a different parent must not silently reorder its new
neighbours -- which is exactly the confusion a single flat list produces.

WHAT MAY HOLD WHAT is authored here rather than inferred, for the reason
`RELATIONSHIP_DOMAIN_RANGE` is: a rule that lives only in whatever the last
caller happened to allow is a rule nobody can argue with. It is deliberately
permissive about the book and strict about nesting depth -- a DM may put their
scene almost anywhere, and may not build a tower of encounters inside
encounters.
"""

from __future__ import annotations

#: The book's own levels, from the harvest's `depth`.
CHAPTER = "chapter"
SECTION = "section"
SUBSECTION = "subsection"

#: What a DM adds. `scene` and `encounter` are the only POSITIONAL kinds: they
#: happen somewhere in the running order. An npc, a monster, a location, an
#: item, a piece of lore and a quest are things the story CONTAINS rather than
#: places in it -- they are reached through the scenes that name them, and
#: giving them a slot in the order would put "a rusty key" between two scenes.
SCENE = "scene"
ENCOUNTER = "encounter"

POSITIONAL = frozenset({CHAPTER, SECTION, SUBSECTION, SCENE, ENCOUNTER})

#: `depth` as the harvester recorded it, to the level it means.
BY_DEPTH = {1: CHAPTER, 2: SECTION, 3: SUBSECTION}

#: kind -> the levels it may sit INSIDE. Empty means top level.
#:
#: A SCENE GOES WHERE A SECTION GOES, because that is what it is: an episode in
#: the run of play, beside the book's own. An ENCOUNTER goes inside a scene or
#: a section, because a fight happens DURING something -- and not inside
#: another encounter, which is a nesting a table has no use for.
MAY_SIT_INSIDE: dict[str, frozenset[str]] = {
    CHAPTER: frozenset(),
    SECTION: frozenset({CHAPTER}),
    SUBSECTION: frozenset({CHAPTER, SECTION}),
    SCENE: frozenset({CHAPTER, SECTION, SUBSECTION}),
    ENCOUNTER: frozenset({SECTION, SUBSECTION, SCENE}),
}


def level_of(kind: str, depth: int | None = None) -> str:
    """What level a thing sits at.

    A campaign section knows its own kind; a canon one knows only its `depth`,
    so both are answered here rather than at each call site guessing.
    """
    if kind in (SCENE, ENCOUNTER):
        return kind
    return BY_DEPTH.get(depth or 0, SECTION)


def may_contain(parent: str, child: str) -> bool:
    """May a `parent`-level thing hold a `child`-level one?

    Answered by asking the CHILD what it may sit inside, because that is the
    direction the rule is authored in and one table is easier to keep honest
    than two that must agree.
    """
    return parent in MAY_SIT_INSIDE.get(child, frozenset())


def refuse(parent_level: str, child_level: str) -> str:
    """Why a move is not allowed, in words a DM would use. `""` when it is.

    Refusals are sentences rather than codes: this reaches a person in a
    tooltip, and "an encounter goes inside a scene, not inside an encounter" is
    the whole explanation.
    """
    if may_contain(parent_level, child_level):
        return ""
    allowed = MAY_SIT_INSIDE.get(child_level, frozenset())
    if not allowed:
        return f"{_a(child_level)} sits at the top and cannot go inside anything"
    return (
        f"{_a(child_level)} goes inside "
        + " or ".join(_a(x) for x in sorted(allowed))
        + f", not inside {_a(parent_level)}"
    )


def _a(word: str) -> str:
    """`an encounter`, not `a encounter`. It is read by a person."""
    return f"{'an' if word[:1] in 'aeiou' else 'a'} {word}"
