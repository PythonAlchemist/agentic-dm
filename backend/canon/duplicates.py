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
    #: The id the survivor should CARRY afterwards, when its current one is
    #: wrong rather than merely one of two. Empty for an ordinary merge, where
    #: the survivor's id is already the id to keep.
    rescope_to: str = ""


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


def plan_globals(entities: list[dict], scheme) -> list[Merge]:
    """Which chapter-scoped nodes the book says are one thing after all.

    `BookScheme.global_names` is the anthology's exception list, and adding a
    name to it changes what a FUTURE ingest mints -- nothing about it reaches a
    graph already loaded. This is the repair for that gap, and it is the reason
    the exception list is worth editing at all.

    THE SURVIVOR'S ID IS WRONG, not merely one of two. An ordinary merge picks
    a winner from ids that already exist; here every candidate is scoped to a
    chapter and the right id is `kftgv:vrakir`, which no node holds. So the
    plan carries `rescope_to` -- the id `mint_id` would produce now -- and the
    apply renames the survivor onto it. Without that the graph and a fresh
    ingest would disagree about a name they both got right.

    THE RICHEST NODE SURVIVES, by mention count then by id. The two halves are
    the same entity, so this only decides which node's edges stay put; taking
    the one the book actually talks about moves the fewest.

    A NAME THE SCHEME DOES NOT CALL GLOBAL IS NOT TOUCHED, and neither is a
    keyed node: the book's own area numbering said those apart, and `Avernus`
    is both the first layer of the Nine Hells and casino area A2.
    """
    from backend.canon.writer import mint_id

    groups: dict[str, list[dict]] = {}
    for entity in entities:
        if not scheme.is_global(entity["name"]) or is_area_keyed(
            entity["id"], entity["name"]
        ):
            continue
        groups.setdefault(normalize(entity["name"]), []).append(entity)

    merges: list[Merge] = []
    for members in groups.values():
        keep_name = _best_name([e["name"] for e in members])
        # No chapter, because a global name has none to be scoped to. If the
        # scheme ever disagreed, `mint_id` would hand back `kftgv::vrakir` --
        # so the shape is checked rather than trusted.
        target = mint_id("", keep_name, scheme=scheme)
        if target.count(":") != 1:
            raise ValueError(f"{keep_name!r} minted {target!r}, which is not book-wide")
        # One node already carrying the right id and nothing to fold into it is
        # a name that was never split. Re-running has to be a no-op or this is
        # not safe to leave in the repair sequence.
        if len(members) == 1 and members[0]["id"] == target:
            continue
        survivor = max(members, key=lambda e: (e.get("mentions", 0), e["id"]))
        merges.append(
            Merge(
                survivor=survivor["id"],
                survivor_name=keep_name,
                losers=tuple(sorted(e["id"] for e in members if e["id"] != survivor["id"])),
                aliases=tuple(sorted({e["name"] for e in members if e["name"] != keep_name})),
                rescope_to=target,
            )
        )
    return sorted(merges, key=lambda m: m.rescope_to)


def is_area_keyed(entity_id: str, name: str) -> bool:
    """Does this id carry the book's OWN area key, or only this code's scoping?

    `is_keyed` asks the coarser question -- does the id have two colons -- and
    for a campaign book that is the same question. In an anthology it is not:
    chapter scoping adds the same colon, so `kftgv:heart-of-ashes:armory` reads
    as keyed while carrying no key at all. That reading is RIGHT for merging
    (two heists' armories are two armories) and wrong here, where the chapter
    scope IS the mistake being repaired.

    Answered against the name rather than by guessing at the tail's shape:
    `mint_id` builds the tail as the key and the name-slug joined, so a tail
    that is exactly the name-slug had no key. `t7-armory` did, `armory` did
    not -- and `Avernus`, casino area A2, is kept out of a rescope that would
    otherwise fold a themed room into the first layer of the Nine Hells.
    """
    from backend.canon.assembler import slugify

    parts = entity_id.split(":")
    return len(parts) >= 3 and parts[-1] != slugify(name)


def plan_merges(entities: list[dict], schemes: dict | None = None) -> list[Merge]:
    """Which nodes to fold together. Pure, so the rule can be tested exactly.

    `entities` are dicts with `id` and `name`. Returns one `Merge` per group
    that needs one, ordered by survivor id so two runs plan identically.

    `schemes` maps a book prefix to its `BookScheme`, and IS WHAT KEEPS THIS OFF
    A NAME THE BOOK DECLARES BOOK-WIDE. Keyed by prefix rather than passed as a
    single scheme because this reads the whole plane at once, and the caller
    should not have to run it per book to be safe. It
    became necessary the moment `plan_globals` started rescoping them. The rule
    below reads "one unkeyed member, some keyed" as a place and its own area
    entry, which held while an unkeyed id could only mean book-global in a
    campaign book. After a rescope it can also mean a name an anthology shares:
    `kftgv:avernus` is the first layer of the Nine Hells and
    `kftgv:the-stygian-gambit:a2-avernus` is a themed casino floor, and this
    planned to fold the second into the first.

    Two statements make that a refusal rather than a judgement call. The
    allowlist says the name identifies ONE thing across chapters; the key says
    the book numbered THIS one as its own area. Both are authored, and together
    they say these are different things -- so the group is skipped, and skipped
    silently, since there is nothing here for a human to decide.
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
        scheme = (schemes or {}).get(members[0]["id"].split(":")[0])
        if scheme is not None and scheme.is_global(members[0]["name"]):
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
