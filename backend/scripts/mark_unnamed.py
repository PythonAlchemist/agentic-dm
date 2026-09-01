"""Record on each canon entity whether the book actually names it.

    uv run python -m backend.scripts.mark_unnamed            # plan
    uv run python -m backend.scripts.mark_unnamed --apply

THE ALTERNATIVE TO DELETING THEM, and the reason `drop_unsupported` is not the
answer to the seventh invariant. 154 canon entities hold no mention, so they
cite no prose: the extractor title-cased common nouns the book writes only in
lowercase, and it authored names for things the book describes without naming.
The first instinct was to remove them. The DM's ruling was that they are worth
keeping -- `Monodrones GUARDS Abacus Car` says something true about a real
train car, and deleting the node to tidy a scan throws that away.

SO THE DEFECT IS RESTATED. It was never that these nodes exist. It is that a
read could not tell them from an entity the book names, and telling those apart
is the one promise this project makes. This writes that distinction down.

IT SETS FALSE AND CLEARS, AND NEVER SETS TRUE. An entity a mention names needs
no property to say so, because the mention IS the saying; a second record of
the same fact is a second place for it to go wrong. See `schema.NAMED_BY_BOOK`.

IT CLEARS AS WELL AS SETS, which is the half that keeps it honest. An entity
that earns a mention -- from a new alias, a re-scan, a chapter written since --
is named by the book now, and a stale `named_by_book: false` on it would be the
graph lying in the safe direction. Both moves are counted and printed.

ONLY THE BOOK'S OWN PROSE COUNTS, and the plane on every `Mention` here is
what says so. `expand` fleshes an entity out into a CAMPAIGN-plane section and
writes a campaign-plane mention pointing at it -- and the entity it expands is
often the book's. A mention is a mention to Cypher, so a query that does not
name the plane reads the DM's generated scene as the book naming the thing and
clears the mark. That is this project's promise failing in the direction
nobody would check: a canon node quietly taking on the book's authority from
prose written last night.

IT TOUCHES NO EDGE, NO MENTION AND NO NAME. One property, on entities of the
canon plane, and nothing else.
"""

from __future__ import annotations

import argparse

from backend.canon.writer import CANON_PLANE
from backend.core.database import neo4j_session, read_only_session
from backend.graph.schema import NAMED_BY_BOOK

#: Unmarked and unnamed: the rows the invariant fails on.
TO_MARK = f"""
MATCH (e:Entity {{plane:$plane}})
WHERE NOT (e)<-[:REFERS_TO]-(:Mention {{plane:$plane}}) AND e.{NAMED_BY_BOOK} IS NULL
  AND ($prefix = '' OR e.id STARTS WITH $prefix)
RETURN e.id AS id, e.name AS name,
       [l IN labels(e) WHERE l <> 'Entity'] AS kind
ORDER BY e.id
"""

#: Marked but named after all -- the mark went stale and would now be a lie.
TO_CLEAR = f"""
MATCH (e:Entity {{plane:$plane}})<-[:REFERS_TO]-(:Mention {{plane:$plane}})
WHERE e.{NAMED_BY_BOOK} IS NOT NULL
  AND ($prefix = '' OR e.id STARTS WITH $prefix)
// DISTINCT BECAUSE THE JOIN IS ONE ROW PER MENTION. Without it four entities
// holding eleven mentions between them were reported as eleven entities, and
// the write then cleared four -- a count that described the join rather than
// the work, the same way `check_invariants` once described its LIMIT.
RETURN DISTINCT e.id AS id, e.name AS name,
       [l IN labels(e) WHERE l <> 'Entity'] AS kind
ORDER BY e.id
"""

MARK = f"""
MATCH (e:Entity {{plane:$plane}}) WHERE e.id IN $ids
  AND NOT (e)<-[:REFERS_TO]-(:Mention {{plane:$plane}})
SET e.{NAMED_BY_BOOK} = false
RETURN count(*) AS n
"""

CLEAR = f"""
MATCH (e:Entity {{plane:$plane}}) WHERE e.id IN $ids
  AND (e)<-[:REFERS_TO]-(:Mention {{plane:$plane}})
REMOVE e.{NAMED_BY_BOOK}
RETURN count(*) AS n
"""


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--book", default="", help="Book slug, e.g. kftgv. "
                        "Omitted means every book.")
    parser.add_argument("--plane", default=CANON_PLANE)
    parser.add_argument("--apply", action="store_true",
                        help="Without this nothing is written.")
    args = parser.parse_args()

    params = {"plane": args.plane, "prefix": f"{args.book}:" if args.book else ""}
    with read_only_session() as session:
        mark = [dict(r) for r in session.run(TO_MARK, params)]
        clear = [dict(r) for r in session.run(TO_CLEAR, params)]

    where = args.book or "every book"
    print(f"{where}:")
    print(f"  {len(mark)} entities no section names, not yet saying so")
    print(f"  {len(clear)} marked entities that a mention now names")
    for row in mark[:15]:
        kind = row["kind"][0] if row["kind"] else "-"
        print(f"    mark   {kind:9} {row['name']!r}")
    if len(mark) > 15:
        print(f"           ... and {len(mark) - 15} more")
    for row in clear[:15]:
        print(f"    clear  {row['name']!r}")

    if not args.apply:
        print("\n  Nothing was written. Re-run with --apply.")
        return 0

    # THE PREDICATE IS RE-STATED IN THE WRITE. The read and the write are two
    # transactions, and an entity that earned a mention in between must not be
    # marked on the strength of a stale read.
    with neo4j_session() as session:
        marked = session.run(
            MARK, {"plane": args.plane, "ids": [r["id"] for r in mark]}
        ).single()["n"] if mark else 0
        cleared = session.run(
            CLEAR, {"plane": args.plane, "ids": [r["id"] for r in clear]}
        ).single()["n"] if clear else 0

    print(f"\n  marked {marked}, cleared {cleared}")
    if marked != len(mark) or cleared != len(clear):
        print("  the difference gained or lost a mention between "
              "the read and the write, and was left alone")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
