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

CO-OCCURRENCE IS RECOMPUTED FOR THE SECTIONS THAT GAINED A MENTION, and only
those. A redeemed entity that joined the mention triangle but gained no
`CO_OCCURS_WITH` edge would be citable and disconnected -- present in a passage
and absent from every sentence-level neighbourhood the retriever walks. The
recomputation reads ALL of an affected section's mentions, not only the new
one, because a pair is a fact about a sentence rather than about the mention
that happened to arrive last. `_write_co_occurrence` MERGEs on the pair and
carries no properties, so redoing a section's edges is idempotent.

WHAT IT STILL DOES NOT UPDATE: passage derivations, which are computed on a
full write. A redeemed entity is citable and connected; its passages are the
ones the next write derives.

THE DEFAULT TARGET IS `named_by_book: false` -- the entities `mark_unnamed`
recorded as citing nothing. Those are exactly the ones an alias might redeem,
and an entity that already has mentions has nothing to gain here.
"""

from __future__ import annotations

import argparse

from backend.canon.cooccurrence import plan_co_occurrences
from backend.canon.spine import (
    AliasUse,
    EntityNames,
    WriteMention,
    WriteSection,
    mention_id,
    scan_mentions,
)
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
#: Every mention already in a section, so a recomputed co-occurrence describes
#: the whole sentence rather than only what just arrived.
SECTION_MENTIONS = """
MATCH (m:Mention {plane:$plane})-[:IN_SECTION]->(s:Section)
WHERE s.id IN $sections
MATCH (m)-[:REFERS_TO]->(e:Entity)
RETURN s.id AS section, m.id AS id, e.id AS entity, e.name AS entity_name,
       coalesce(m.offsets, []) AS offsets,
       coalesce(m.occurrences, 1) AS occurrences,
       coalesce(m.display_name, e.name) AS surface,
       coalesce(m.chapter_slug, '') AS chapter
"""

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
    pairs = _recompute_co_occurrence(
        sorted({m.section_id for _, m in found}), by_chapter, args.plane)
    print(f"\n  wrote {written} mention(s), {pairs} co-occurrence pair(s). "
          "Run `mark_unnamed --apply` to clear the mark from anything that can "
          "now cite the book.")
    return 0


def _recompute_co_occurrence(section_ids, by_chapter, plane: str) -> int:
    """Redo the sentence-level pairs for the sections that gained a mention.

    ALL OF A SECTION'S MENTIONS, not only the new one: a pair is a fact about a
    sentence, and computing it from the arrival alone would record the new
    entity's neighbours and silently drop everyone else's.
    """
    from backend.canon.writer import _write_co_occurrence

    if not section_ids:
        return 0
    sections = {s.id: s for group in by_chapter.values() for s in group}
    wanted = [sections[sid] for sid in section_ids if sid in sections]

    with read_only_session() as session:
        rows = [dict(r) for r in session.run(
            SECTION_MENTIONS, {"plane": plane, "sections": section_ids})]
    mentions = [
        WriteMention(
            id=r["id"], entity_id=r["entity"], section_id=r["section"],
            chapter_slug=r["chapter"], occurrences=r["occurrences"],
            offsets=tuple(r["offsets"]), entity_name=r["entity_name"],
            section_heading=sections[r["section"]].heading if r["section"] in sections else "",
            uses=(AliasUse(name=r["surface"], occurrences=r["occurrences"]),),
        )
        for r in rows if r["section"] in sections
    ]
    planned = plan_co_occurrences(wanted, mentions)
    with neo4j_session() as session:
        for pair in planned:
            session.execute_write(lambda tx, p=pair: _write_co_occurrence(tx, p))
    return len(planned)


if __name__ == "__main__":
    raise SystemExit(main())
