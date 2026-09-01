"""Mint the mentions a newly authored alias makes findable, and nothing else.

    uv run python -m backend.scripts.redeem_unnamed                 # plan
    uv run python -m backend.scripts.redeem_unnamed --apply
    uv run python -m backend.scripts.redeem_unnamed --entity cos:gunther-arasek

THE HALF `sync_authored_aliases` REFUSES TO DO, and it says so: adding a
spelling fixes RESOLUTION immediately -- a lookup naming `Gunther` now reaches
the man -- while the mentions "arrive with the next full write". That is the
right caution for a re-write, which re-derives canon and re-seeds a running
order the DM has edited. It is too much caution for this: an alias the book
demonstrably writes, matched by the same scanner, in the same chapters, adding
mentions that did not exist.

WHY IT IS NEEDED. `Gunther Arasek` is a real man in a real stockyard and held
no mention at all, because the book writes "Gunther and Yelena Arasek" and his
own name is never one run of text. So did Davian Martikov's daughter
`Stefania`, and `Brom`, and `Anna Krezkova` whose node dropped the feminine
ending. Four people the graph could not cite a word about.

IT ONLY EVER ADDS. Nothing is deleted, repointed or renamed, so an entity that
already cites prose cannot lose any -- which is the difference between this and
`homebrew.rescan`, whose whole job is to reconcile. A mention this creates is
one the scanner would have produced on a full write and did not, because the
spelling was not there to look for yet.

WHAT IT DOES NOT UPDATE, stated plainly: co-occurrence edges and passage
derivations are computed on a full write and are not recomputed here. A
redeemed entity is citable and joins the mention triangle; it does not gain the
`CO_OCCURS_WITH` edges a re-write would have given it. That is a smaller gap
than not being able to cite the book at all, and it is a gap.

THE DEFAULT TARGET IS `named_by_book: false` -- the entities `mark_unnamed`
recorded as citing nothing. Those are exactly the ones an alias might redeem,
and an entity that already has mentions has nothing to gain here.
"""

from __future__ import annotations

import argparse

from backend.canon.spine import EntityNames, WriteSection, mention_id, scan_mentions
from backend.canon.writer import CANON_PLANE
from backend.core.database import neo4j_session, read_only_session
from backend.graph.schema import NAMED_BY_BOOK

TARGETS = f"""
MATCH (e:Entity {{plane:$plane}})
WHERE ($ids = [] AND e.{NAMED_BY_BOOK} = false) OR e.id IN $ids
OPTIONAL MATCH (a:Alias)-[:ALIAS_OF]->(e)
RETURN e.id AS id, e.name AS name, collect(a.name) AS aliases
ORDER BY e.id
"""

SECTIONS = """
MATCH (c:Chapter)-[:HAS_SECTION]->(s:Section {plane:$plane})
RETURN c.slug AS chapter, s.id AS id, s.heading AS heading, s.text AS text,
       coalesce(s.index, 0) AS ix, coalesce(s.depth, 0) AS depth,
       coalesce(s.parent_index, -1) AS parent, coalesce(s.key, '') AS key
"""

#: MERGE, never CREATE. Two runs of this are one run, and a mention that
#: already exists is left exactly as the write that made it left it.
WRITE = """
MATCH (e:Entity {id:$entity}), (s:Section {id:$section})
MERGE (m:Mention {id:$id})
ON CREATE SET m.plane = $plane, m.chapter_slug = $chapter,
              m.occurrences = $occurrences, m.offsets = $offsets,
              m.display_name = $display_name
MERGE (m)-[:REFERS_TO]->(e)
MERGE (m)-[:IN_SECTION]->(s)
RETURN count(m) AS n
"""


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--entity", action="append", default=[],
                        help="Entity id to try. Repeatable. Defaults to every "
                             "entity marked as unnamed by the book.")
    parser.add_argument("--plane", default=CANON_PLANE)
    parser.add_argument("--apply", action="store_true",
                        help="Without this nothing is written.")
    args = parser.parse_args()

    with read_only_session() as session:
        targets = [
            EntityNames(id=r["id"], name=r["name"],
                        aliases=tuple(a for a in (r["aliases"] or []) if a))
            for r in session.run(TARGETS, {"plane": args.plane, "ids": args.entity})
        ]
        by_chapter: dict[str, list[WriteSection]] = {}
        for r in session.run(SECTIONS, {"plane": args.plane}):
            by_chapter.setdefault(r["chapter"], []).append(WriteSection(
                id=r["id"], chapter_slug=r["chapter"], heading=r["heading"] or "",
                index=r["ix"], depth=r["depth"], parent_index=r["parent"],
                text=r["text"] or "", key=r["key"] or ""))
        held = {r["id"] for r in session.run(
            "MATCH (m:Mention {plane:$plane}) RETURN m.id AS id",
            {"plane": args.plane})}

    print(f"{len(targets)} entities to try, across {len(by_chapter)} chapters")
    found: list[tuple[EntityNames, object]] = []
    for entity in targets:
        for chapter, sections in by_chapter.items():
            # `scan_mentions` applies `scannable_here` itself, so a
            # chapter-scoped entity is looked for only in its own chapter and
            # this loop cannot reintroduce the violations just repaired.
            for mention in scan_mentions(sections, [entity], chapter_slug=chapter):
                if mention_id(entity.id, mention.section_id) not in held:
                    found.append((entity, mention))

    by_entity: dict[str, list] = {}
    for entity, mention in found:
        by_entity.setdefault(entity.name, []).append(mention)
    print(f"  {len(found)} mention(s) the book supports and the graph lacks, "
          f"for {len(by_entity)} entit(y/ies)\n")
    for name, mentions in sorted(by_entity.items()):
        spellings = sorted({m.uses[0].name for m in mentions if m.uses})
        print(f"  {name!r}: {len(mentions)} mention(s) as {spellings}")
        for m in mentions[:4]:
            print(f"      {m.section_heading!r}")

    if not args.apply:
        print("\n  Nothing was written. Re-run with --apply.")
        return 0

    written = 0
    with neo4j_session() as session:
        for entity, m in found:
            written += session.run(WRITE, {
                "entity": entity.id, "section": m.section_id, "id": m.id,
                "plane": args.plane, "chapter": m.chapter_slug,
                "occurrences": m.occurrences, "offsets": list(m.offsets),
                "display_name": m.uses[0].name if m.uses else entity.name,
            }).single()["n"]
    print(f"\n  wrote {written} mention(s). Run `mark_unnamed --apply` to clear "
          "the mark from anything that can now cite the book.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
