"""Find entities holding mentions in adventures their own scope forbids.

    uv run python -m backend.scripts.audit_scope --book kftgv

REPORTS, NEVER WRITES. There are two different repairs behind one symptom and
nothing here can tell them apart, so it prints the evidence and stops -- the
convention this package already keeps for aliases and edges.

THE INVARIANT. `spine.scannable_in` lets a chapter-scoped id match only inside
its own chapter: `kftgv:axe-from-the-grave:honorary-mayor-jenna-bean` is Axe
from the Grave's, and thirteen heists' worth of `Guard` and `Kitchen` stay
apart because of it. So a mention of that entity in `tockworths-clockworks` is
not something the scan could have produced. It got there another way.

THE WAY IT GOT THERE is an alias merge. `apply_aliases` folds a group onto one
survivor and carries the losers' mentions over -- and when the group spanned
adventures, so do the mentions. `Heist`, `The Heist`, `Planning the Heist`,
`Casino Heist` and `Vidorant's Next Heist` came back from the coreference model
as one thing, and one QUEST node scoped to the Stygian Gambit ended up holding
the jobs of four adventures.

THE TWO REPAIRS, and why a human picks:

  * A BAD MERGE. The names were never one thing and the foreign mentions
    belong to an entity that no longer exists. `split_entity` pulls it back
    out; the foreign mentions go with it.

  * A NAME THE BOOK USES BOOK-WIDE. A crime syndicate really does appear in
    several heists, and the entity is scoped too narrowly rather than merged
    too widely. `merge_duplicates --globals` rescopes it, and the mentions were
    right all along.

Deleting the foreign mentions is the wrong answer to the second case and would
be indistinguishable from the first at the moment of deleting, which is why
this writes nothing.
"""

from __future__ import annotations

import argparse
import re
from collections import defaultdict

from backend.canon.aliases import normalize
from backend.canon.lookup import CANON_PLANE
from backend.core.database import read_only_session

#: A KEYED AREA, read off the id. `mint_id` resolves a keyed place to
#: `(book, chapter, key)` rather than to its name, so `c10-laundry-room` and
#: `b3-prison-tower` carry their map key in the last segment.
#:
#: This is one of the TWO verdicts that need no judgement -- see
#: `_names_its_own_room` for the other, which catches the commoner shape this
#: rule cannot reach: an unkeyed entity holding a mention that spells someone
#: else's keyed room. The book keys rooms PER
#: ADVENTURE -- `C10` is a room in Axe from the Grave and `C10` in another
#: heist is a different room -- so a keyed area is never a name the book uses
#: book-wide, and a foreign mention of one is always a bad merge. It is also
#: the anthology rule's original example: thirteen heists' worth of `Guard` and
#: `Kitchen`.
_KEYED = re.compile(r"^[a-z]{1,2}\d+[a-z]?-")


def _heading_name(heading: str, key: str) -> str:
    """`Rooftop` for `C18: Rooftop`. The key is stripped, not re-derived."""
    found = re.match(rf"\s*{re.escape(key)}\s*[.:)\-]?\s*", heading.strip(), re.I)
    return heading.strip()[found.end():].strip() if found else ""


def _same_noun(left: str, right: str) -> bool:
    """`Stone Golem` and `Stone Golems` are one name, for this report's purpose.

    A TRAILING `s` IS FOLDED HERE AND NOWHERE ELSE. `aliases.normalize` folds
    only typographic differences on purpose -- its whole claim is that a reader
    can see the entire rule in one place and check that nothing fuzzy has crept
    into it -- and a plural rule is exactly the fuzz it refuses. It is safe in
    this file because nothing here writes: the fold only decides which of two
    sentences a person is shown before making the call themselves.
    """
    left, right = normalize(left), normalize(right)
    return left == right or left.rstrip("s") == right.rstrip("s")


def _spells_another_name(name: str, where_seen) -> str:
    """A foreign surface that is not this entity's name, or `""`.

    THE SIGNAL THE MENTION COUNT WAS STANDING IN FOR. Counting was the first
    thing tried and it is wrong about most of what it decides: of the 16 pairs
    it called "may be book-wide", 13 were plain bad merges. What actually
    separates them was one field away the whole time -- WHETHER THE FOREIGN
    MENTION EVEN SPELLS THIS ENTITY'S NAME.

    Measured on this book: 29 of 34 (entity, foreign surface) pairs spell a
    DIFFERENT name, and reading them settles each one on sight.
    `Honorary Mayor Jenna Bean` holding ten `Mayor Broadfoot`s is two mayors of
    two towns; `The Celestial Codex` holding `Celestial` matched a LANGUAGE in
    a list of languages a modron speaks; `Erinyes Statuette` holding
    `Erinyes Barracks` matched a room.

    IT IS EVIDENCE, NOT A VERDICT. A different spelling of one real thing --
    `Anna Krezkov` against the book's `Anna Krezkova` -- would read the same
    way here, so this prints what the section says and leaves the call to a
    person. That is the difference from the arithmetic it replaces, which
    printed a conclusion it had not earned.
    """
    for where in where_seen or ():
        surface = (where.get("surface") or "").strip()
        if surface and not _same_noun(surface, name):
            return surface
    return ""


def _names_its_own_room(where_seen) -> str:
    """The keyed room a foreign mention is actually naming, or `""`.

    THE SECOND VERDICT THAT NEEDS NO JUDGEMENT, and the one `_KEYED` above
    could not reach. That rule reads the ENTITY's id, so it fires only when the
    entity is itself a keyed area -- and the commonest shape here is the other
    way round: an unkeyed entity holding a mention that sits in someone else's
    keyed room AND SPELLS THAT ROOM'S NAME. `Flat Rooftop` holding a `Rooftop`
    in `C18: Rooftop`, `Erinyes Statuette` holding an `Erinyes Barracks` in
    `B15: Erinyes Barracks`, `Varkenbluff University` holding a `Zoo` in
    `T8: Zoo`.

    The book keys rooms PER ADVENTURE, so a room is one adventure's and the
    mention is of the room. Three fewer things for a person to decide.

    IT IS THE SURFACE THAT MUST MATCH, not merely the section being keyed. A
    book-wide name is perfectly entitled to appear inside a keyed room -- the
    Golden Vault is named in plenty of them -- and firing on that would call
    every such mention a bad merge.
    """
    for where in where_seen or ():
        key = (where.get("key") or "").strip()
        if not key:
            continue
        room = _heading_name(where.get("heading") or "", key)
        surface = (where.get("surface") or "").strip()
        if room and normalize(surface) == normalize(room):
            return where.get("heading") or room
    return ""


_FOREIGN = """
MATCH (m:Mention {plane:$plane})-[:REFERS_TO]->(e:Entity {plane:$plane})
WHERE e.id STARTS WITH $prefix
MATCH (m)-[:IN_SECTION]->(sec:Section)
MATCH (c:Chapter)-[:HAS_SECTION]->(sec)
WITH e, c.slug AS found_in, count(m) AS mentions,
     // `sec.key` was computed by the one `KEYED_HEADING` match that minted the
     // room, so reading it back is not a second parse of the same heading.
     collect({surface: m.display_name, key: sec.key, heading: sec.heading})
       AS where_seen,
     CASE WHEN size(split(e.id, ':')) > 2 THEN split(e.id, ':')[1] ELSE '' END AS scope
WHERE scope <> '' AND found_in <> scope
RETURN e.id AS id, e.name AS name, scope, found_in, mentions, where_seen
ORDER BY e.id, found_in
"""

#: Mentions the entity has AT HOME. Printed as evidence, NOT as the verdict:
#: counting was the first thing tried here and it is wrong about exactly the
#: cases the anthology rule exists for. `Laundry Room` has one mention at home
#: and two abroad, which arithmetic reads as book-wide and a human reads as a
#: room in one heist. `_KEYED` decides those; this number only helps with the
#: rest, where a person still has to look.
_AT_HOME = """
MATCH (m:Mention {plane:$plane})-[:REFERS_TO]->(e:Entity {id:$id})
MATCH (m)-[:IN_SECTION]->(sec:Section)
MATCH (c:Chapter)-[:HAS_SECTION]->(sec)
WHERE c.slug = $scope
RETURN count(m) AS n
"""


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--book", default="kftgv", help="Book slug, e.g. kftgv")
    parser.add_argument("--plane", default=CANON_PLANE)
    args = parser.parse_args()

    with read_only_session() as session:
        rows = [
            dict(r)
            for r in session.run(
                _FOREIGN, {"plane": args.plane, "prefix": f"{args.book}:"}
            )
        ]
        at_home = {
            row["id"]: session.run(
                _AT_HOME, {"plane": args.plane, "id": row["id"], "scope": row["scope"]}
            ).single()["n"]
            for row in rows
        }

    by_entity: dict[str, list[dict]] = defaultdict(list)
    for row in rows:
        by_entity[row["id"]].append(row)

    print(f"{len(rows)} (entity, foreign adventure) pairs across "
          f"{len(by_entity)} entities in {args.book}")
    if not rows:
        print("  the anthology scope holds everywhere. Nothing to decide.")
        return
    print()
    for entity_id, found in sorted(by_entity.items()):
        home = at_home[entity_id]
        abroad = sum(f["mentions"] for f in found)
        # THE KEYED CASE IS DECIDED; THE REST IS A GUESS, PRINTED AS ONE.
        # Counting mentions was the first thing tried here and it is wrong
        # about exactly the cases the anthology rule exists for: `Laundry Room`
        # with one mention at home and two abroad reads as "book-wide" to
        # arithmetic and is obviously a room in one heist to a reader.
        room = ""
        for where in found:
            room = room or _names_its_own_room(where.get("where_seen"))
        if _KEYED.match(entity_id.rsplit(":", 1)[-1]):
            reads_as = "BAD MERGE -- a keyed area belongs to one adventure"
        elif room:
            reads_as = f"BAD MERGE -- that mention names {room!r}, one room"
        else:
            other = ""
            for where in found:
                other = other or _spells_another_name(found[0]["name"], where.get("where_seen"))
            reads_as = (
                f"the foreign mention spells {other!r}, not this name"
                if other
                else "the same name recurring -- a common noun, and this book "
                     "keys those per adventure"
            )
        print(f"  {found[0]['name']}")
        print(f"    {entity_id}")
        print(f"    {home} at home in {found[0]['scope']}, {abroad} abroad -- reads as {reads_as}")
        for f in found:
            # WHAT THE SECTION ACTUALLY SAYS, which is the field that decides
            # nearly all of these and was not printed until now.
            spellings = sorted({
                (w.get("surface") or "").strip()
                for w in (f.get("where_seen") or ()) if (w.get("surface") or "").strip()
            })
            says = f" -- as {', '.join(repr(x) for x in spellings)}" if spellings else ""
            print(f"      {f['mentions']:3} in {f['found_in']}{says}")
    print()
    print("  Nothing was written. A bad merge is undone with `split_entity`;")
    print("  a name the book uses book-wide is rescoped with")
    print("  `merge_duplicates --globals`.")


if __name__ == "__main__":
    main()
