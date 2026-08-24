"""Which of a book's entity names are the same thing said differently.

THREE RULE-BASED ATTEMPTS FAILED AT THIS, each in a different place, and the
sequence is the argument for the file.

`duplicates.py` folds names differing by a leading article, which is real and
narrow: it never touches `Varkenbluff Museum of Natural History`,
`Varkenbluff Museum`, `Varkenbluff` and `Museum`, four nodes for one building.
The anthology allowlist matched an exact spelling and so made `the Golden
Vault` global while leaving thirteen `Golden Vault` nodes scoped per adventure
-- the line meant to keep the organisation whole shattered it. Article-stripping
that allowlist fixed the scoping and still left two ids, because `mint_id`
slugifies the name and the article survives into the slug.

Each fix closed one spelling family. The next family needed another rule.

AND ONE CASE NO RULE CAN REACH. `the vault` is Vidorant's physical vault in one
adventure and, in another, the organisation that commissioned the heist. The
strings are identical. Nothing about the characters distinguishes them and
everything about the sentence does, which is a reading task.

WHAT THIS IS NOT ALLOWED TO DO. `cooccurrence.py` records four expensive
failures at automating a NEIGHBOURING judgement -- consensus voting, a wiki
oracle, type constraints, two-stage classification -- all of them trying to
infer a typed relationship from the fact that two names share a sentence. That
is unverifiable and this is not: a grouping is a claim a reader checks in
seconds, it is bounded to names already extracted, and the answer harness can
now measure whether applying it helped. So the model GROUPS NAMES IT IS GIVEN
and does nothing else. It never invents a name, never types an entity, never
proposes a relationship, and its output is a seed file somebody reads before
anything touches the graph -- the same standing as `location-subtypes.yaml`.
"""

from __future__ import annotations

import json
import re
from collections.abc import Iterable, Sequence
from dataclasses import dataclass

#: Words that make two names look alike without being evidence of anything.
#: Deliberately tiny: the blocking step only has to avoid asking about every
#: pair, and a word wrongly left in costs one extra question rather than a
#: wrong answer.
_STOPWORDS = frozenset(
    {"the", "a", "an", "of", "and", "or", "in", "on", "at", "to", "for", "s"}
)

_WORD = re.compile(r"[^\W_]+", re.UNICODE)


def significant_words(name: str) -> frozenset[str]:
    """The words in a name that could tie it to another name."""
    return frozenset(
        word.casefold()
        for word in _WORD.findall(name)
        if word.casefold() not in _STOPWORDS
    )


def weak_words(names: Sequence[str], *, common: int = 6) -> frozenset[str]:
    """Words that group names WITHOUT being evidence they are one thing.

    Blocking on a shared word assembles a list and asks a model which of it is
    the same thing. Do that with `hallway` and the list is five different
    hallways -- a question that invites the answer it got: `Arrow Slit
    Hallway`, `Access Hallway`, `Dining Hallway` and `Upper Hallway` came back
    as one room. The model was answering the question I asked.

    A word is weak when it is BOTH frequent and used as a common noun. Both
    halves are needed: `vidorant` appears in fourteen names of this corpus and
    is the strongest blocking word it has, because it is a person's name and
    never written lowercase. `room`, `hall`, `key` and `vault` appear lowercase
    somewhere, which is the book saying they are kinds of thing rather than
    names of one.

    A RULE ABOUT WHAT TO ASK, not about what the answer is. That division is
    the point: cheap rules choose the questions, the model makes the judgment,
    and a reader checks it.
    """
    seen: dict[str, int] = {}
    lowercased: set[str] = set()
    for name in names:
        for word in _WORD.findall(name):
            folded = word.casefold()
            if folded in _STOPWORDS:
                continue
            seen[folded] = seen.get(folded, 0) + 1
            if word[:1].islower():
                lowercased.add(folded)
    return frozenset(
        word for word, count in seen.items()
        if count > common and word in lowercased
    )


def blocks(
    names: Iterable[str], *, cap: int = 40, common: int = 6
) -> list[tuple[str, tuple[str, ...]]]:
    """Names that COULD be one thing, grouped by a word they share.

    A BLOCKING STEP, not an answer. Asking a model about all pairs of 1,575
    names is a million questions; asking it about the names that share a word
    is a few hundred, and two names for one thing in this corpus always share
    one -- `Varkenbluff Museum` and `Museum`, `Curator Alda Arkin` and `Alda`.

    A name appears in every block its words put it in, so a decision is never
    lost because the blocking picked the wrong word. The model sees the same
    name more than once and the caller merges what comes back.

    `cap` drops blocks too large to ask about in one prompt -- a word like
    `vault` in a heist anthology. Dropped LOUDLY by the caller rather than
    silently: an unasked block is a question nobody answered, not a no.

    Returns `(word, names)` sorted, so two runs propose the same work.
    """
    names = list(names)
    weak = weak_words(names, common=common)
    by_word: dict[str, set[str]] = {}
    for name in names:
        for word in significant_words(name):
            if word in weak:
                continue
            by_word.setdefault(word, set()).add(name)
    return sorted(
        (word, tuple(sorted(group)))
        for word, group in by_word.items()
        if 2 <= len(group) <= cap
    )


@dataclass(frozen=True)
class AliasGroup:
    """One thing, and every name this book calls it.

    `canonical` is one OF the names rather than a new one: a model that may
    write a name is a model that may write a name the book never used, and
    then the scan looks for something that is not there.
    """

    canonical: str
    names: tuple[str, ...]

    @property
    def others(self) -> tuple[str, ...]:
        return tuple(n for n in self.names if n != self.canonical)


PROMPT = """\
These names were extracted from one D&D adventure book. Some of them are
different ways of writing the SAME thing.

Group only the names that refer to the same entity. Use the book's own
conventions: a title and a bare name are one person (`Curator Alda Arkin`,
`Alda Arkin`, `Alda`); a full place name and its short form are one place
(`Varkenbluff Museum of Natural History`, `Varkenbluff Museum`).

DO NOT group:
- two different things that share a word (`Security Key` and `Master Key`)
- a thing and the place it is in, or a thing and a quest about it
  (`Murkmire Stone` and `Steal the Murkmire Stone` are an item and a task)
- names you are merely unsure about. Leaving a name ungrouped is the safe
  answer and costs nothing.

Pick `canonical` from the names given -- the fullest, most specific one. Never
write a name that is not in the list.

Names:
{names}

Return JSON: {{"groups": [{{"canonical": "...", "names": ["...", "..."]}}]}}
Return {{"groups": []}} if none of them are the same thing.
"""


def parse(payload: str, offered: Sequence[str]) -> tuple[list[AliasGroup], list[str]]:
    """Read one response. Returns `(groups, refusals)`.

    EVERY NAME IS CHECKED AGAINST WHAT WAS OFFERED, and a group naming anything
    else is refused whole rather than trimmed. A model that invented one name
    was not reading the list, and keeping the rest of that group would be
    trusting the half of an answer that happened to look right.

    Refusals are returned rather than logged, for the reason every filter in
    this package reports its drops: a grouping nobody was told about is
    indistinguishable from one that was never proposed.
    """
    try:
        raw = json.loads(payload)
    except json.JSONDecodeError as exc:
        return [], [f"unparseable response: {exc}"]

    allowed = set(offered)
    groups: list[AliasGroup] = []
    refused: list[str] = []
    for entry in raw.get("groups") or []:
        names = tuple(dict.fromkeys(entry.get("names") or ()))
        canonical = entry.get("canonical") or ""
        invented = [n for n in names if n not in allowed]
        if invented:
            refused.append(f"invented {invented!r} in {list(names)!r}")
            continue
        if canonical not in names:
            refused.append(f"canonical {canonical!r} not among {list(names)!r}")
            continue
        if len(names) < 2:
            refused.append(f"a group of one: {list(names)!r}")
            continue
        groups.append(AliasGroup(canonical=canonical, names=names))
    return groups, refused


def merge_overlapping(groups: Iterable[AliasGroup]) -> list[AliasGroup]:
    """Fold groups that share a name, since a name is asked about many times.

    `Varkenbluff Museum` is in the `varkenbluff` block and the `museum` block,
    so two answers can each carry part of the family. Transitive by design:
    if A groups with B and B with C, all three are one thing.

    The canonical is the LONGEST name in the union, which is the same rule the
    prompt asks for and is applied here again because two answers may disagree
    about which of them was fullest.
    """
    parent: dict[str, str] = {}

    def find(name: str) -> str:
        parent.setdefault(name, name)
        while parent[name] != name:
            parent[name] = parent[parent[name]]
            name = parent[name]
        return name

    for group in groups:
        first = group.names[0]
        for name in group.names[1:]:
            parent[find(first)] = find(name)

    families: dict[str, set[str]] = {}
    for name in parent:
        families.setdefault(find(name), set()).add(name)

    return sorted(
        (
            AliasGroup(
                canonical=max(sorted(names), key=len),
                names=tuple(sorted(names)),
            )
            for names in families.values()
            if len(names) > 1
        ),
        key=lambda g: g.canonical,
    )
