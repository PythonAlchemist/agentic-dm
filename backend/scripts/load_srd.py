#!/usr/bin/env python3
"""Load the System Reference Document as the rules everybody may read.

    uv run python -m backend.scripts.load_srd --dry-run
    uv run python -m backend.scripts.load_srd --apply

WHY THIS BOOK IS DIFFERENT FROM THE OTHERS. Curse of Strahd and Keys from the
Golden Vault are behind a token because they are books a reader has to own. The
SRD is published under a licence that permits copying and redistribution, which
is exactly why it can be the material a player sees without their DM revealing
it one spell at a time. The licence IS the reason, so it is recorded on the
`:Book` node rather than in a comment here -- `reference: true` is what
`player/reader.py` reads, and `licence` is why that mark is allowed to be there.

NO MODEL RUNS. `canon/srd.py` reads the headings the document already prints.
The adventure pipeline pays a vision model per page because narrative prose
hides its entities; a spell called `Fireball` under a heading called `Fireball`
hides nothing, and asking a model would be paying to introduce error.

IT REPLACES ITSELF. Loading twice is loading once: everything under the `srd:`
prefix is removed first, in one transaction, so a re-run after a parser fix
does not leave the old reading alongside the new one.

IT CANNOT TOUCH AN ADVENTURE. Every write here is keyed to the `srd:` prefix
and the delete is bounded by it, so the blast radius is this book.
"""

from __future__ import annotations

import argparse
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from backend.canon.assembler import slugify
from backend.canon.srd import read
from backend.core.database import neo4j_session

PREFIX = "srd"
TITLE = "System Reference Document 5.1"

#: WHAT MAKES IT PUBLIC, in the words of the document itself. Recorded on the
#: node so a reader auditing why the rules are visible to players finds the
#: answer beside the mark rather than in a commit message.
LICENCE = "Open Gaming License v1.0a"
ATTRIBUTION = (
    "System Reference Document 5.1 Copyright 2023, Wizards of the Coast, LLC. "
    "Authors Mike Mearls, Jeremy Crawford, Chris Perkins, Rodney Thompson, "
    "Peter Lee, James Wyatt, Robert J. Schwalb, Bruce R. Cordell, "
    "Chris Sims, and Steve Townshend, based on original material by "
    "E. Gary Gygax and Dave Arneson."
)

CLEAR = """
MATCH (n) WHERE n.id STARTS WITH $prefix DETACH DELETE n
RETURN count(n) AS n
"""

CLEAR_BOOK = "MATCH (b:Book {slug:$slug}) DETACH DELETE b RETURN count(b) AS n"

BOOK = """
MERGE (b:Book {slug:$slug})
SET b.id = $slug, b.title = $title, b.display_name = $title,
    b.plane = 'canon',
    // THE MARK THAT MAKES IT PUBLIC, and the reason it is allowed.
    b.reference = true, b.licence = $licence, b.attribution = $attribution
RETURN b.slug AS slug
"""

CHAPTER = """
MATCH (b:Book {slug:$slug})
MERGE (c:Chapter {id:$id})
SET c.slug = $chapter, c.title = $title, c.index = $index, c.plane = 'canon'
MERGE (b)-[:HAS_CHAPTER]->(c)
RETURN c.id AS id
"""

#: One entry becomes three things that already mean something in this graph: a
#: `:Section` holding the prose, an `:Entity` that is the thing itself, and the
#: `:Mention` joining them.
#:
#: THE MENTION IS WHAT MAKES IT FINDABLE. `player/retrieval.py` reaches a
#: passage through `(entity)<-[:REFERS_TO]-(mention)-[:IN_SECTION]->(section)`,
#: so an entry with no mention is a spell a player can name and not read.
#: A LABEL CANNOT BE A PARAMETER in Cypher, so the kind is interpolated -- and
#: the only values that reach that interpolation are these four, checked
#: against this tuple before the query is built. Nothing a caller supplies gets
#: near it.
KINDS = ("SPELL", "ITEM", "MONSTER", "RULE")

#: One entry becomes three things that already mean something in this graph: a
#: `:Section` holding the prose, an `:Entity` that is the thing itself, and the
#: `:Mention` joining them.
#:
#: THE MENTION IS WHAT MAKES IT FINDABLE. `player/retrieval.py` reaches a
#: passage through `(entity)<-[:REFERS_TO]-(mention)-[:IN_SECTION]->(section)`,
#: so an entry with no mention is a spell a player can name and not read.

ENTRY_PLAIN = """
MATCH (c:Chapter {id:$chapter_id})
CREATE (s:Section {
  id:$section_id, heading:$name, text:$text, plane:'canon',
  index:$index, chapter_slug:$chapter
})
MERGE (c)-[:HAS_SECTION]->(s)
CREATE (e:Entity:%s {id:$entity_id, name:$name, plane:'canon', kind:$kind,
                     status:'accepted'})
CREATE (m:Mention {id:$mention_id, plane:'canon', occurrences:1,
                   offsets:[0], display_name:$name, scanned:true})
CREATE (m)-[:REFERS_TO]->(e)
CREATE (m)-[:IN_SECTION]->(s)
CREATE (s)-[:DESCRIBES]->(e)
RETURN e.id AS id
"""

ALIAS = """
MATCH (e:Entity {id:$entity_id})
MERGE (a:Alias {name:$name})
ON CREATE SET a.normalized = $normalized, a.plane = 'canon'
MERGE (a)-[:ALIAS_OF]->(e)
"""


def load(pdf: Path, apply: bool) -> dict:
    from backend.canon.aliases import normalize

    report = read(pdf)
    counts = Counter(e.kind for e in report.entries)
    totals = {
        "entries": len(report.entries), "chapters": len(report.chapters),
        "dropped_footers": report.dropped_footers,
        "dropped_page_numbers": report.dropped_page_numbers,
        "passed_over": report.passed_over, **counts,
    }
    if not apply:
        return totals

    # NAMES COLLIDE ACROSS KINDS. `Shield` is a spell and a piece of armour;
    # `Giant Rat` appears twice in the monster lists. An id that is only the
    # slug would silently drop one of them, so a repeat takes a suffix and the
    # count of them is reported rather than swallowed.
    seen: Counter[str] = Counter()
    with neo4j_session() as session:
        removed = session.execute_write(
            lambda tx: tx.run(CLEAR, {"prefix": f"{PREFIX}:"}).single()["n"])
        session.execute_write(
            lambda tx: tx.run(CLEAR_BOOK, {"slug": PREFIX}).single()["n"])
        totals["removed_first"] = removed

        session.execute_write(lambda tx: tx.run(BOOK, {
            "slug": PREFIX, "title": TITLE, "licence": LICENCE,
            "attribution": ATTRIBUTION}).consume())

        chapters = {}
        for index, title in enumerate(report.chapters):
            slug = slugify(title)
            chapter_id = f"{PREFIX}:{slug}"
            session.execute_write(lambda tx, i=index, t=title, s=slug,
                                  cid=chapter_id: tx.run(CHAPTER, {
                                      "slug": PREFIX, "id": cid, "chapter": s,
                                      "title": t, "index": i}).consume())
            chapters[title] = (chapter_id, slug)

        duplicates = 0
        for index, entry in enumerate(report.entries):
            if entry.chapter not in chapters or entry.kind not in KINDS:
                continue
            chapter_id, chapter_slug = chapters[entry.chapter]
            slug = slugify(entry.name)
            seen[slug] += 1
            if seen[slug] > 1:
                slug = f"{slug}-{seen[slug]}"
                duplicates += 1
            entity_id = f"{PREFIX}:{slug}"
            section_id = f"{PREFIX}:{chapter_slug}#{index}"
            session.execute_write(lambda tx, e=entry, eid=entity_id,
                                  sid=section_id, cid=chapter_id,
                                  cs=chapter_slug, i=index: tx.run(
                                      ENTRY_PLAIN % e.kind, {
                                          "chapter_id": cid, "section_id": sid,
                                          "entity_id": eid, "name": e.name,
                                          "text": e.text, "kind": e.kind,
                                          "index": i, "chapter": cs,
                                          "mention_id": f"{eid}@{sid}",
                                      }).consume())
            session.execute_write(lambda tx, eid=entity_id, n=entry.name:
                                  tx.run(ALIAS, {
                                      "entity_id": eid, "name": n,
                                      "normalized": normalize(n)}).consume())
        totals["duplicate_names"] = duplicates
    return totals


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pdf", default="data/SRD-OGL_V5.1.pdf")
    parser.add_argument("--apply", action="store_true",
                        help="write it; without this nothing is stored")
    args = parser.parse_args()

    pdf = Path(args.pdf)
    if not pdf.exists():
        print(f"no such file: {pdf}", file=sys.stderr)
        return 1

    totals = load(pdf, apply=args.apply)
    for key in sorted(totals):
        print(f"  {key:22} {totals[key]}")
    print("\nnothing written -- pass --apply" if not args.apply
          else f"\nwritten as '{PREFIX}', marked reference under {LICENCE}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
