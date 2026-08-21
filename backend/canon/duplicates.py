"""One place, minted twice. Which nodes are the same thing, and which are not.

`mint_id` names the risk this repairs, in its own docstring: "An unkeyed place
has no key to resolve to and falls back to its name like everything else, which
is the riskiest case here and the one to watch." Watched, and measured, across
909 canon entities:

    29 groups  every member keyed          distinct rooms -- LEAVE THEM
    16 groups  one unkeyed, some keyed     a place and its own area entry
     3 groups  every member unkeyed        differ only by a leading "The"

THE 29 ARE NOT A DEFECT AND MERGING THEM WOULD BE ONE. `Kitchen` is six rooms
in four buildings, `Chapel` is the one in Castle Ravenloft and the one in the
village, and `mint_id` keys them apart on purpose -- a name-only id "would
merge three rooms into one and silently delete two of those edges". Nothing
here touches a group whose members are all keyed.

THE OTHER 19 ARE ONE PLACE EACH. `cos:svalich-woods` and
`cos:the-lands-of-barovia:c-svalich-woods` are the same woods; the second is
only where the book happens to describe it. Every one of the 16 was read by
hand before this rule was written, and none was a false pair.

WHY THIS IS NOT IN THE WRITER. The two halves are minted by different
chapters -- the unkeyed node by whichever chapter's extraction first named the
place, the keyed one by the chapter that heads it as an area -- so a
per-chapter write cannot see the collision it is half of. The unification is
book-level or it is nothing.

THE SURVIVOR IS THE UNKEYED NODE. Its id says what the thing IS; the keyed id
says which chapter got to it first, which is real but is not identity. The
Svalich Woods are not the property of `the-lands-of-barovia`.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

#: A leading article is never part of what a place IS. `The Amber Temple` and
#: `Amber Temple` are one temple; the book uses both within a paragraph.
_ARTICLE = re.compile(r"^the\s+", re.IGNORECASE)


def normalize(name: str) -> str:
    """The key two names share when they name one thing.

    Deliberately NOT `aliases.normalize`, which folds punctuation for the
    resolver's benefit. This is a coarser question -- are these two nodes the
    same node -- and folding more aggressively here would start merging things
    the resolver is right to keep apart.
    """
    return _ARTICLE.sub("", name.strip()).casefold()


def is_keyed(entity_id: str) -> bool:
    """`cos:<chapter>:<key>-<slug>` rather than `cos:<slug>`.

    A keyed id resolves to (book, chapter, key) and is the book's own area
    numbering. Two of them are two rooms, whatever they are called.
    """
    return entity_id.count(":") >= 2


@dataclass(frozen=True)
class Merge:
    """One survivor, and the nodes to fold into it."""

    survivor: str
    survivor_name: str
    losers: tuple[str, ...]
    #: Every name in the group other than the survivor's, to be kept as aliases
    #: so a question spelling it the old way still resolves.
    aliases: tuple[str, ...]


def _best_name(names: list[str]) -> str:
    """The name to keep: no leading article, and not the lowercase spelling.

    `shrine of Mother Night` and `Shrine of Mother Night` are the same shrine
    and the second is how the book heads it. Ties go to the shorter string,
    then alphabetically, so the choice is total and a re-run is stable.
    """
    return min(
        names,
        key=lambda n: (
            bool(_ARTICLE.match(n)),
            not n[:1].isupper(),
            len(n),
            n,
        ),
    )


def plan_merges(entities: list[dict]) -> list[Merge]:
    """Which nodes to fold together. Pure, so the rule can be tested exactly.

    `entities` are dicts with `id` and `name`. Returns one `Merge` per group
    that needs one, ordered by survivor id so two runs plan identically.
    """
    groups: dict[str, list[dict]] = {}
    for entity in entities:
        groups.setdefault(normalize(entity["name"]), []).append(entity)

    merges: list[Merge] = []
    for members in groups.values():
        if len(members) < 2:
            continue
        unkeyed = [e for e in members if not is_keyed(e["id"])]
        # Every member keyed: distinct rooms that share a name. The whole
        # reason `mint_id` keys places at all.
        if not unkeyed:
            continue

        names = [e["name"] for e in members]
        keep_name = _best_name(names)
        # Among unkeyed nodes the one whose name we are keeping, so the
        # survivor's id and name agree. Falls back to the first by id when the
        # kept name belongs to a keyed node, which happens when the book heads
        # the area better than the loose mention spelled it.
        survivor = next(
            (e for e in sorted(unkeyed, key=lambda e: e["id"]) if e["name"] == keep_name),
            sorted(unkeyed, key=lambda e: e["id"])[0],
        )
        losers = tuple(sorted(e["id"] for e in members if e["id"] != survivor["id"]))
        merges.append(
            Merge(
                survivor=survivor["id"],
                survivor_name=keep_name,
                losers=losers,
                aliases=tuple(sorted({n for n in names if n != keep_name})),
            )
        )
    return sorted(merges, key=lambda m: m.survivor)
