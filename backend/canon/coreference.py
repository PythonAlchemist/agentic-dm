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
from collections.abc import Iterable, Mapping, Sequence
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


#: A name whose entity is one of these is a TASK, and a task is never the thing
#: it is about. `Deliver the key to Varrin Axebreaker` and `Varrin` share two
#: words and are a job and a person.
_TASK_LABELS = frozenset({"QUEST"})


#: Either apostrophe the corpus sets a possessive with. The book uses the curly
#: one and the extractor emits the straight one, the same split `spine` folds.
_POSSESSIVE = re.compile(r"['\u2019]s\b", re.IGNORECASE)


def owns_something(name: str, word: str) -> bool:
    """Is `word` the OWNER in this name rather than the thing named?

    `Constantori` and `Constantori's Portrait` share a word, so blocking offers
    them together and the model merges a person with their portrait. It did
    that to `Agile Hand` and its guildhouse, and to Gwish and his room, his
    trunk and his raven.

    True when the word appears before a possessive marker: `Constantori's
    Portrait` is about a portrait, `Constantori` is about a man. False when the
    word comes after one -- in `Vidorant's Vault` the word `vault` is the thing
    owned, and whether that is the same vault as `Vault` is a real question
    worth asking.
    """
    match = _POSSESSIVE.search(name)
    if match is None:
        return False
    before = name[: match.start()].casefold()
    return word.casefold() in _WORD.findall(before)


def shares_only_a_surname(a: str, b: str) -> bool:
    """Two names ending in the same word but beginning differently.

    A CAMPAIGN HAS FAMILIES, and blocking on a shared word assembles them:
    `Emil Toranescu` and `Zuleika Toranescu`, six Belviews, `Sergei von
    Zarovich` and `Strahd von Zarovich`. Asked which of those are the same
    thing, the model merged all of them -- including the two brothers whose
    quarrel is the entire campaign.

    A surname means RELATED, not identical, which is the `hallway` failure
    wearing a proper noun. The given name is the discriminating position, so
    names that differ there are different people however much else they share.

    `Varkenbluff Museum of Natural History` and `Varkenbluff Museum` begin
    alike and are untouched; `Old Svalich Road` and `Winding Road` do not, and
    are correctly kept apart.
    """
    first = [w.casefold() for w in _WORD.findall(a)]
    second = [w.casefold() for w in _WORD.findall(b)]
    if len(first) < 2 or len(second) < 2:
        return False
    if first[-1] != second[-1] or first[0] == second[0]:
        return False
    # A TITLE MAKES THE FIRST WORDS DIFFER WITHOUT MAKING TWO PEOPLE.
    # `Curator Alda Arkin` and `Alda Arkin` are one woman, and she is the
    # family this whole pipeline was built to find. Where one name is the
    # other with words in front, it is the same name said longer -- which
    # needs no list of titles to know, and so cannot be defeated by a title
    # nobody wrote down.
    shorter, longer = sorted((first, second), key=len)
    return longer[-len(shorter):] != shorter


def _partition(name: str, kinds: "Mapping[str, frozenset[str]] | None") -> str:
    """`task` or `thing`. Blocks never mix the two.

    AT BLOCKING, not at validation, for the reason `weak_words` is: a question
    that offers a quest beside its object invites the answer it gets, and the
    prompt forbidding it did not stop the model doing it fourteen times. Asked
    only about quests, the same model groups two spellings of one quest, which
    is right and useful.
    """
    if not kinds:
        return "thing"
    return "task" if kinds.get(name, frozenset()) & _TASK_LABELS else "thing"


def blocks(
    names: Iterable[str],
    *,
    cap: int = 40,
    common: int = 6,
    kinds: "Mapping[str, frozenset[str]] | None" = None,
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
    by_word: dict[tuple[str, str], set[str]] = {}
    for name in names:
        kind = _partition(name, kinds)
        for word in significant_words(name):
            if word in weak:
                continue
            # An owner and what they own are never offered together, so the
            # side depends on the WORD as well as the name: `Gwish` is plain
            # everywhere, `Gwish's raven` is possessed under `gwish` and plain
            # under `raven`.
            side = f"{kind}/owned" if owns_something(name, word) else kind
            by_word.setdefault((word, side), set()).add(name)
    out = []
    for (word, side), group in by_word.items():
        # A block whose members merely share a surname is a family, and asking
        # about it invites the answer it got. Split so each given name is asked
        # about on its own -- two spellings of ONE person still block together,
        # because they begin alike.
        for family in _by_given_name(sorted(group)):
            if 2 <= len(family) <= cap:
                out.append(
                    (word if side == "thing" else f"{word}/{side}", tuple(family))
                )
    return sorted(out)


def _by_given_name(group: list[str]) -> list[list[str]]:
    """Split a block so no two members share only a surname."""
    families: list[list[str]] = []
    for name in group:
        for family in families:
            if not any(shares_only_a_surname(name, other) for other in family):
                family.append(name)
                break
        else:
            families.append([name])
    return families


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


def merge_overlapping(
    groups: Iterable[AliasGroup], *, cap: int = 6
) -> tuple[list[AliasGroup], list[str]]:
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

    kept, runaway = [], []
    for names in families.values():
        if len(names) < 2:
            continue
        # A RUNAWAY IS NOT AN ANSWER. Folding is transitive, so one wrong
        # grouping welds two families together and the union keeps growing:
        # a single bad link chained Little Lockford, Brimstone Hold, Vrakir's
        # Chamber and the Ashen Creatures into one 28-name "entity". A real
        # alias family is two to five names. Refused whole and reported,
        # because trimming it would mean guessing which of the links was the
        # bad one.
        if len(names) > cap:
            runaway.append(
                f"{len(names)} names folded into one family, refused: "
                f"{sorted(names)[:4]}..."
            )
            continue
        kept.append(
            AliasGroup(
                canonical=max(sorted(names), key=len), names=tuple(sorted(names))
            )
        )
    return sorted(kept, key=lambda g: g.canonical), runaway
