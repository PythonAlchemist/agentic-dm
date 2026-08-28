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

from backend.canon.lookup import CANON_PLANE
from backend.core.database import read_only_session

#: A KEYED AREA, read off the id. `mint_id` resolves a keyed place to
#: `(book, chapter, key)` rather than to its name, so `c10-laundry-room` and
#: `b3-prison-tower` carry their map key in the last segment.
#:
#: This is the one verdict that needs no judgement. The book keys rooms PER
#: ADVENTURE -- `C10` is a room in Axe from the Grave and `C10` in another
#: heist is a different room -- so a keyed area is never a name the book uses
#: book-wide, and a foreign mention of one is always a bad merge. It is also
#: the anthology rule's original example: thirteen heists' worth of `Guard` and
#: `Kitchen`.
_KEYED = re.compile(r"^[a-z]{1,2}\d+[a-z]?-")


_FOREIGN = """
MATCH (m:Mention {plane:$plane})-[:REFERS_TO]->(e:Entity {plane:$plane})
WHERE e.id STARTS WITH $prefix
MATCH (m)-[:IN_SECTION]->(sec:Section)
MATCH (c:Chapter)-[:HAS_SECTION]->(sec)
WITH e, c.slug AS found_in, count(m) AS mentions,
     CASE WHEN size(split(e.id, ':')) > 2 THEN split(e.id, ':')[1] ELSE '' END AS scope
WHERE scope <> '' AND found_in <> scope
RETURN e.id AS id, e.name AS name, scope, found_in, mentions
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
        if _KEYED.match(entity_id.rsplit(":", 1)[-1]):
            reads_as = "BAD MERGE -- a keyed area belongs to one adventure"
        else:
            reads_as = "bad merge?" if home > abroad else "may be book-wide?"
        print(f"  {found[0]['name']}")
        print(f"    {entity_id}")
        print(f"    {home} at home in {found[0]['scope']}, {abroad} abroad -- reads as {reads_as}")
        for f in found:
            print(f"      {f['mentions']:3} in {f['found_in']}")
    print()
    print("  Nothing was written. A bad merge is undone with `split_entity`;")
    print("  a name the book uses book-wide is rescoped with")
    print("  `merge_duplicates --globals`.")


if __name__ == "__main__":
    main()
